"""Conservative, day-first English grocery receipt parsing for manual review."""

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
import re

MONEY = r'(?<![\d.,])(?:[£€$]\s*)?(\d+[.,]\d{2})(?![\d.,])'
END_AMOUNT = re.compile(MONEY + r'\s*[A-Za-z]?\s*$')
TOTAL = re.compile(r'^(?:grand\s+total|total(?:\s+(?:due|to\s+pay))?|amount\s+due|balance\s+due)\s*:?\s*(?:(?:GBP|EUR|USD)\s*)?(?=[£€$\d])', re.I)
TOTAL_LABEL = re.compile(r'^(?:grand\s+total|total(?:\s+(?:due|to\s+pay))?|amount\s+due|balance\s+due)\s*:?$', re.I)
SUMMARY = re.compile(r'^(?:sub\s*total|total|grand total|amount due|balance due|cash|change|card|visa|mastercard|payment|vat|tax|tendered)\b', re.I)
NON_ITEM = re.compile(r'\b(?:savings?|discount|coupon|balance|loyalty|clubcard|nectar|points|refund)\b', re.I)
LIDL_PRICE = re.compile(r'^[£€$]?\s*(\d+[.,]\d{2})\s+[A-Z]\s*$')
LIDL_QUANTITY = re.compile(r'^(\d+(?:\.\d+)?)\s*(kg)?\s*[x×]\s*[£€$]?\s*(\d+[.,]\d{2})$', re.I)
LIDL_DISCOUNT = re.compile(r'(?:^|\s)-\s*[£€$]?(\d+[.,]\d{2})\s*$')
SUPERMARKETS = (
    (r'\bTESCO\b', 'Tesco'), (r"\bSAINSBURY(?:['’]?S)?\b", "Sainsbury's"),
    (r'\bALDI\b', 'Aldi'), (r'\bLIDL\b', 'Lidl'), (r'\bASDA\b', 'Asda'),
    (r'\bMORRISONS\b', 'Morrisons'), (r'\bWAITROSE\b', 'Waitrose'),
    (r'\bM\s*&\s*S\b|\bMARKS\s*(?:&|AND)\s*SPENCER\b', 'M&S'),
    (r'\bCO[ -]?OP\b', 'Co-op'), (r'\bICELAND\b', 'Iceland'),
    (r'\bOCADO\b', 'Ocado'),
)


@dataclass
class ParsedItem:
    raw_description: str
    quantity: float
    unit_price_minor: int | None
    line_total_minor: int
    discount_minor: int = 0


@dataclass
class ParsedReceipt:
    supermarket_name: str | None = None
    purchase_date: str | None = None
    currency: str | None = None
    total_minor: int | None = None
    items: list[ParsedItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def minor_units(value: str) -> int:
    return int(Decimal(value.replace(',', '.')) * 100)


def lidl_product_line(line: str) -> bool:
    """Identify a Lidl product description when OCR separates its price line."""
    if not re.search(r'[A-Za-z]', line):
        return False
    if line.startswith(tuple('0123456789')) or '×' in line or re.search(r'\bkg\b', line, re.I):
        return False
    if SUMMARY.match(line) or NON_ITEM.search(line) or re.search(
        r'\b(?:lidl\s+plus|receipt|not sales|belfast|gb\d|price of|win one|enter:)\b', line, re.I,
    ):
        return False
    return line.upper() not in {'GBP', 'A', 'C'}


def lidl_nearby_candidates(candidates: dict[int, str], index: int) -> list[int]:
    """Order nearby Lidl descriptions by distance, then prior visual row."""
    return sorted(
        (position for position in candidates if abs(position - index) <= 3),
        key=lambda position: (abs(position - index), position > index),
    )


def parse_lidl_items(lines: list[str]) -> list[ParsedItem]:
    """Parse Lidl's column-ordered price, quantity and Lidl Plus discount rows."""
    summary_index = next((index for index, line in enumerate(lines) if TOTAL.match(line) or TOTAL_LABEL.fullmatch(line)), len(lines))
    candidates = {index: line for index, line in enumerate(lines[:summary_index]) if lidl_product_line(line)}
    drafts = {}
    price_candidates = {}
    for index, line in enumerate(lines[:summary_index]):
        match = LIDL_PRICE.fullmatch(line)
        if not match:
            continue
        candidate = next((position for position in lidl_nearby_candidates(candidates, index) if position not in drafts), None)
        if candidate is None:
            continue
        drafts[candidate] = {
            'line_total_minor': minor_units(match[1]),
            'quantity': 1.0,
            'unit_price_minor': None,
            'discount_minor': 0,
            'price_position': index,
        }
        price_candidates[index] = candidate

    for index, line in enumerate(lines[:summary_index]):
        quantity = LIDL_QUANTITY.fullmatch(line)
        if quantity:
            candidate = next(iter(lidl_nearby_candidates(candidates, index)), None)
            if candidate in drafts:
                drafts[candidate]['quantity'] = float(quantity[1])
                drafts[candidate]['unit_price_minor'] = minor_units(quantity[3])
            continue
        discount = LIDL_DISCOUNT.search(line)
        if not discount:
            continue
        previous_price = next((position for position in range(index - 1, -1, -1) if position in price_candidates), None)
        if previous_price is not None:
            drafts[price_candidates[previous_price]]['discount_minor'] += minor_units(discount[1])

    return [
        ParsedItem(
            candidates[candidate], draft['quantity'], draft['unit_price_minor'],
            draft['line_total_minor'], draft['discount_minor'],
        )
        for candidate, draft in sorted(drafts.items(), key=lambda entry: entry[1]['price_position'])
    ]


def parse_receipt(text: str) -> ParsedReceipt:
    result = ParsedReceipt()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header = '\n'.join(lines[:8])
    stores = {name for pattern, name in SUPERMARKETS if re.search(pattern, header, re.I)}
    if len(stores) == 1:
        result.supermarket_name = stores.pop()

    dates = set()
    for match in re.finditer(r'\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b', text):
        if match[1]:
            year, month, day = map(int, match.group(1, 2, 3))
        else:
            day, month, year = map(int, match.group(4, 5, 6))
            if year < 100:
                year += 2000
        try:
            dates.add(date(year, month, day).isoformat())
        except ValueError:
            continue
    if len(dates) == 1:
        result.purchase_date = dates.pop()
    elif len(dates) > 1:
        result.warnings.append('Multiple dates found; confirm the purchase date.')

    currencies = set()
    for pattern, code in [(r'£|\bGBP\b', 'GBP'), (r'€|\bEUR\b', 'EUR'), (r'\bUSD\b', 'USD')]:
        if re.search(pattern, text, re.I):
            currencies.add(code)
    if len(currencies) == 1:
        result.currency = currencies.pop()
    elif len(currencies) > 1:
        result.warnings.append('Conflicting currencies found.')

    totals = set()
    summary_started = False
    for index, line in enumerate(lines):
        amount = END_AMOUNT.search(line)
        if TOTAL.match(line) and amount:
            totals.add(minor_units(amount[1]))
            summary_started = True
            continue
        if TOTAL_LABEL.fullmatch(line) and index + 1 < len(lines):
            following_amount = END_AMOUNT.fullmatch(lines[index + 1])
            if following_amount:
                totals.add(minor_units(following_amount[1]))
                summary_started = True
                continue
        if SUMMARY.match(line):
            summary_started = True
            continue
        if not amount:
            continue
        prefix = line[:amount.start()].strip()
        if result.supermarket_name == 'Lidl' and LIDL_DISCOUNT.search(line):
            continue
        if NON_ITEM.search(line) or prefix.endswith('-'):
            result.warnings.append(f'Adjustment/discount requires review: {line}')
            continue
        if summary_started:
            continue
        if not re.search(r'[A-Za-z]', prefix) or re.search(r'\b\d{1,4}[/\-]\d{1,2}[/\-]\d{1,4}\b', prefix):
            continue
        quantity = Decimal(1)
        unit_price = None
        # Explicit quantities only; do not infer weighted quantities or discounts.
        detailed = re.fullmatch(r'(.+?)\s+(\d+(?:\.\d+)?)\s*[xX@]\s*([£€$]?\s*\d+[.,]\d{2})', prefix)
        leading = re.fullmatch(r'(\d+(?:\.\d+)?)\s*[xX]\s+(.+)', prefix)
        if detailed:
            prefix, quantity_text, unit_text = detailed.groups()
            quantity = Decimal(quantity_text)
            unit_price = minor_units(re.sub(r'[£€$\s]', '', unit_text))
        elif leading:
            quantity = Decimal(leading[1])
            prefix = leading[2]
        if quantity <= 0:
            result.warnings.append(f'Invalid quantity requires review: {line}')
            continue
        total = minor_units(amount[1])
        if unit_price is not None and Decimal(unit_price) * quantity != total:
            result.warnings.append(f'Quantity and unit price do not match line total: {line}')
        result.items.append(ParsedItem(prefix, float(quantity), unit_price, total))

    if result.supermarket_name == 'Lidl':
        lidl_items = parse_lidl_items(lines)
        if lidl_items:
            result.items = lidl_items

    if len(totals) == 1:
        result.total_minor = totals.pop()
    elif len(totals) > 1:
        result.warnings.append('Conflicting receipt totals found.')
    for key in ('supermarket_name', 'purchase_date', 'currency', 'total_minor'):
        if getattr(result, key) is None:
            result.warnings.append(f'{key} was not identified; manual review is required.')
    if not result.items:
        result.warnings.append('No grocery item lines identified.')
    elif result.total_minor is not None and sum(item.line_total_minor - item.discount_minor for item in result.items) != result.total_minor:
        result.warnings.append('Item totals do not match the receipt total; check discounts, taxes and missing lines.')
    return result
