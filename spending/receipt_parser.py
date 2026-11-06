"""Conservative, day-first English grocery receipt parsing for manual review."""

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
import re

MONEY = r'(?<![\d.,])[£€$]\s*(\d+[.,]\d{2})(?![\d.,])'
END_AMOUNT = re.compile(MONEY + r'\s*[A-Za-z]?\s*$')
TOTAL = re.compile(r'\b(?:grand\s+total|total|amount\s+due|balance\s+due)\b', re.I)
TOTAL_DISCOUNT = re.compile(r'\b(?:total\s+(?:savings?|discounts?)|you\s+saved)\b', re.I)
VOUCHER = re.compile(r'\b(?:coupons?|vouchers?)(?:\s*/\s*(?:coupons?|vouchers?))?\b', re.I)
SUMMARY = re.compile(
    r'^(?:sub\s*total|total|grand total|amount due|balance due|cash(?:\s*back)?|'
    r'change|card|visa|mastercard|payment|vat|tax|tendered)\b', re.I,
)
SPLIT_PRICE = re.compile(r'^[£€$]\s*(\d+[.,]\d{2})\s*(?:[A-Z])?\s*$')
EACH_PRICE = re.compile(r'^[£€$]\s*(\d+[.,]\d{2})\s+each\s*$', re.I)
SPLIT_DISCOUNT = re.compile(r'(?:^|\s)-\s*[£€$]\s*(\d+[.,]\d{2})\s*$')
QUANTITY_PRICE = re.compile(
    r'^(\d+)\s*(?:[x×@]\s*)?[£€$]\s*(\d+[.,]\d{2})\s*(?:[A-Z])?$', re.I,
)
WEIGHT_PRICE = re.compile(
    r'^(\d+(?:[.,]\d+)?)\s*(?:kg|g)\s*[x×@]\s*(\d+[.,]\d{2})\s*(?:GBP|EUR|USD)?$', re.I,
)
QUANTITY_PRICE_DISCOUNT = re.compile(
    r'^(\d+)\s*[x×@]\s*(\d+[.,]\d{2})(?:\s+-\s*[£€$]\s*(\d+[.,]\d{2}))?$', re.I,
)
NOW_PRICE = re.compile(r'^(.+?)\s+(?:[£€$]\s*)?(\d+[.,]\d{2})\s+NOW\b', re.I)
EMBEDDED_WEIGHT_PRICE = re.compile(
    r'^(.+?)\s+(\d+(?:[.,]\d+)?)\s*(?:kg|g)\s*[x×@]\s*(\d+[.,]\d{2})\s*(?:GBP|EUR|USD)?$', re.I,
)
LEADING_QUANTITY = re.compile(r'^(\d+)\s+(?![x×@]\b)(?=[A-Za-z])(.+)$', re.I)
PROMOTION_FOR = re.compile(
    r'^(?P<prefix>.*?)\b(?P<count>\d+)\s*(?:for|fr)\s*'
    r'(?:[£€$]\s*)?(?P<price>\d+(?:[.,]\d{1,2})?)(?:\s+[*A-Za-z]+)*\s*$', re.I,
)
PROMOTION_CC = re.compile(
    r'^cc\b.*?(?:[£€$]\s*)?(?P<price>\d+(?:[.,]\d{0,2})?)\s*$', re.I,
)
DISCOUNT_LABEL = re.compile(
    r'\b(?:savings?|offers?|promotions?|discount|clubcard|nectar|lidl\s+plus)\b', re.I,
)
PRINTED_SAVING = re.compile(r'^savings?\b.*?[£€$]\s*(\d+[.,]\d{2})\s*$', re.I)
SPLIT_SUMMARY = re.compile(r'^(?:sub\s*total|total|grand\s+total)\b', re.I)
SUMMARY_PREFIX = re.compile(r'^\s*(?:(?:[^\w\s]+|\d{1,3})\s+)+')
SUPERMARKETS = (
    (r'\bTESCO\b', 'Tesco'), (r"\bSAINSBURY(?:['’]?S)?\b", "Sainsbury's"),
    (r'\bALDI\b', 'Aldi'), (r'\bLIDL\b', 'Lidl'), (r'\bASDA\b', 'Asda'),
    (r'\bMORRISONS\b', 'Morrisons'), (r'\bWAITROSE\b', 'Waitrose'),
    (r'\bM\s*&\s*S\b|\bMARKS\s*(?:&|AND)\s*SPENCER\b', 'M&S'),
    (r'\bCO[ -]?OP\b', 'Co-op'), (r'\bICELAND\b', 'Iceland'),
    (r'\bOCADO\b', 'Ocado'), (r'\bB\s*&\s*M\b|\bB\s+M\b', 'B&M'),
    (r'\bBOOTS(?:\s+UK\s+LIMITED)?\b', 'Boots'),
    (r'\bHOTEL\s+CHOCOLAT\b', 'Hotel Chocolat'),
)
STORE_FORMAT = re.compile(r'\b(?:extra|express|superstore|supermarket|local|metro|market)\b', re.I)
HEADER_METADATA = re.compile(r'\b(?:receipt|questions|visit|https?://|www\.|vat\s*(?:number)?|gb\d)\b', re.I)
MONTHS = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7,
    'july': 7, 'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
    'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12,
    'december': 12,
}
MONTH_NAME = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
COMPACT_MONTH_NAME = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|0ct|Nov|Dec)'


@dataclass
class ParsedDiscount:
    amount_pence: int
    reason: str | None
    source_text: str
    promotion_group: str | None = None


@dataclass
class ParsedPromotion:
    group: str
    marker_text: str
    advertised_quantity: int | None
    advertised_price_pence: int


@dataclass
class ParsedItem:
    raw_description: str
    quantity: float
    unit_price_pence: int | None
    original_pence: int
    discount_pence: int = 0
    discounts: list[ParsedDiscount] = field(default_factory=list)
    promotions: list[ParsedPromotion] = field(default_factory=list)


@dataclass
class ParsedReceipt:
    supermarket_name: str | None = None
    supermarket_location: str | None = None
    purchase_date: str | None = None
    date_candidates: list[str] = field(default_factory=list)
    currency: str | None = None
    total_pence: int | None = None
    total_discount_pence: int = 0
    receipt_discount_pence: int = 0
    items: list[ParsedItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def pence(value: str) -> int:
    return int(Decimal(value.replace(',', '.')) * 100)


def summary_text(line: str) -> str:
    """Remove short OCR/register prefixes before matching payment-summary labels."""
    return SUMMARY_PREFIX.sub('', line).strip()


def is_total_label(line: str) -> bool:
    """Recognise a settlement label anywhere on a summary row, not just at its start."""
    return bool(TOTAL.search(line)) and not TOTAL_DISCOUNT.search(line)


def add_date(dates: set[str], year: int, month: int, day: int) -> None:
    """Add one valid normalised date, expanding receipt-style two-digit years."""
    if year < 100:
        year += 2000
    try:
        dates.add(date(year, month, day).isoformat())
    except ValueError:
        pass


def month_number(value: str) -> int:
    """Resolve a printed month, tolerating OCR's common zero-for-O in 0CT."""
    token = value.casefold()
    if token == '0ct':
        token = 'oct'
    return MONTHS[token]


def normalise_currency_codes(line: str) -> str:
    """Convert an ISO currency immediately followed by an amount to its symbol."""
    symbols = {'gbp': '£', 'eur': '€', 'usd': '$'}
    return re.sub(
        r'\b(GBP|EUR|USD)\s*(\d+[.,]\d{2})(?![\d.,])',
        lambda match: f"{symbols[match[1].casefold()]}{match[2]}",
        line,
        flags=re.I,
    )


def normalise_bare_amounts(lines: list[str], merchant_name: str | None) -> list[str]:
    """Accept bare decimals only when the receipt identifies its store or currency."""
    currency_context = any(
        re.search(r'[£€$]|\b(?:GBP|EUR|USD)\b', line, re.I) for line in lines
    )
    if not currency_context and merchant_name is None:
        return lines

    normalised = []
    for line in lines:
        if PROMOTION_FOR.fullmatch(line) or PROMOTION_CC.fullmatch(line):
            normalised.append(line)
            continue
        line = re.sub(
            r'(?<![\d.,£€$])(-?)(\d+[.,]\d{2})(\s+(?:[A-Z]|NOW))?$',
            lambda match: f"{match[1]}£{match[2]}{match[3] or ''}",
            line,
            flags=re.I,
        )
        normalised.append(line)
    return normalised


def store_location(lines: list[str], store_patterns: list[str]) -> str | None:
    """Extract a readable store location from the header without retailer layouts."""
    store_line = next((index for index, line in enumerate(lines[:8])
                       if any(re.search(pattern, line, re.I) for pattern in store_patterns)), None)
    if store_line is None:
        return None
    for line in lines[store_line + 1:store_line + 7]:
        if HEADER_METADATA.search(line):
            continue
        match = STORE_FORMAT.search(line)
        if match and re.search(r'[A-Za-z]', line[:match.end()]):
            return re.sub(r'\s+', ' ', line[:match.end()]).strip(' -,:')
    return None


def split_product_line(line: str) -> bool:
    """Accept the text immediately before a generic amount as an item name."""
    if not re.search(r'[A-Za-z]', line):
        return False
    if SUMMARY.match(summary_text(line)) or SPLIT_PRICE.fullmatch(line):
        return False
    return True


def split_continuation(line: str) -> bool:
    """Recognise a wrapped continuation without treating every header as a name."""
    return bool(re.match(
        r'^(?:\d+(?:\.\d+)?\s*(?:g|kg|ml|l)\b|flavou?r\b|toilet\b|pack\b|'
        r'blend\b|&\s*|and\b|d\s+)', line, re.I,
    ))


def promotion_marker(line: str) -> tuple[str, int | None, int] | None:
    """Return one generic promotion key, target quantity and advertised price."""
    match = PROMOTION_FOR.fullmatch(line)
    if match:
        quantity = int(match['count'])
        price = pence(match['price']) if re.search(r'[.,]', match['price']) else int(match['price']) * 100
        return f"{quantity}-for-{price}", quantity, price
    match = PROMOTION_CC.fullmatch(line)
    if match:
        price = pence(match['price']) if re.search(r'[.,]', match['price']) else int(match['price']) * 100
        return f"cc-{price}", None, price
    return None


def parse_split_items(lines: list[str]) -> tuple[list[ParsedItem], int, list[str]]:
    """Read generic text, quantity and amount tokens in their OCR order."""
    summary_index = next((index for index, line in enumerate(lines)
                          if SPLIT_SUMMARY.match(summary_text(line))
                          or (VOUCHER.search(summary_text(line)) and END_AMOUNT.search(line))
                          or is_total_label(summary_text(line))), len(lines))
    header_markers = [
        index for index, line in enumerate(lines[:summary_index])
        if re.search(r'\bvat\s*(?:number|no\.?|#)?\b|https?://|www\.', line, re.I)
    ]
    section_start = max(header_markers, default=-1)
    quantity_layout = sum(
        1 for line in lines[section_start + 1:summary_index]
        if LEADING_QUANTITY.match(line) and END_AMOUNT.search(line)
    ) >= 2
    items: list[ParsedItem] = []
    warnings: list[str] = []
    pending_text: list[str] = []
    pending_quantity = 1.0
    pending_unit_price: int | None = None
    open_item: ParsedItem | None = None
    discount_reason: str | None = None
    discount_group: str | None = None
    promotion_number = 0
    active_promotions: dict[str, dict] = {}
    latest_promotions: dict[str, dict] = {}
    orphan_original: int | None = None

    def attach_active_promotions(item: ParsedItem) -> None:
        """Link later items to an open multi-buy group until its quantity is filled."""
        completed = []
        for key, promotion in active_promotions.items():
            group = promotion['group']
            if not any(existing.group == group for existing in item.promotions):
                item.promotions.append(ParsedPromotion(
                    group, promotion['marker_text'], promotion['target'],
                    promotion['advertised_price'],
                ))
                promotion['quantity'] += item.quantity
            if promotion['target'] is not None and promotion['quantity'] >= promotion['target']:
                completed.append(key)
        for key in completed:
            active_promotions.pop(key, None)

    def validate_open_item() -> None:
        if open_item is None or open_item.unit_price_pence is None or open_item.quantity <= 1:
            return
        expected_from_unit = round(open_item.quantity * open_item.unit_price_pence)
        expected_from_first = round(open_item.quantity * open_item.original_pence)
        if expected_from_unit == open_item.original_pence:
            return
        if expected_from_first == open_item.unit_price_pence:
            open_item.original_pence, open_item.unit_price_pence = (
                open_item.unit_price_pence, open_item.original_pence,
            )
            return
        warnings.append(
            f'Item {len(items)} quantity × unit price does not match its original amount.'
        )

    def start_item(name: str, quantity: float, unit_price: int | None, original: int) -> ParsedItem:
        nonlocal open_item, discount_reason, discount_group
        validate_open_item()
        open_item = ParsedItem(name.strip(), quantity, unit_price, original)
        items.append(open_item)
        attach_active_promotions(open_item)
        discount_reason = open_item.promotions[-1].marker_text if open_item.promotions else None
        discount_group = open_item.promotions[-1].group if open_item.promotions else None
        return open_item

    for index in range(section_start + 1, summary_index):
        line = lines[index]
        now_price = NOW_PRICE.match(line)
        if now_price:
            line = f'{now_price[1]} £{now_price[2]}'
        discount = SPLIT_DISCOUNT.search(line)
        marker_text = line[:discount.start()].strip() if discount else line
        if (discount and not QUANTITY_PRICE_DISCOUNT.fullmatch(line)
                and orphan_original is not None and split_product_line(marker_text)
                and not DISCOUNT_LABEL.search(marker_text)):
            start_item(marker_text, 1.0, None, orphan_original)
            orphan_original = None
        marker = promotion_marker(marker_text)
        if marker:
            key, target_quantity, advertised_price = marker
            promotion = active_promotions.get(key)
            previous = latest_promotions.get(key)
            if (promotion is None and previous is not None and open_item is not None
                    and any(existing.group == previous['group'] for existing in open_item.promotions)):
                promotion = previous
            if promotion is None:
                promotion_number += 1
                promotion = {
                    'group': f'promotion-{promotion_number}',
                    'quantity': 0.0,
                    'target': target_quantity,
                    'marker_text': marker_text,
                    'advertised_price': advertised_price,
                }
                active_promotions[key] = promotion
                latest_promotions[key] = promotion
            if open_item is not None:
                group = promotion['group']
                if not any(existing.group == group for existing in open_item.promotions):
                    open_item.promotions.append(ParsedPromotion(
                        group, marker_text, target_quantity, advertised_price,
                    ))
                    promotion['quantity'] += open_item.quantity
                discount_group = group
                if target_quantity is None or promotion['quantity'] >= target_quantity:
                    active_promotions.pop(key, None)
            discount_reason = marker_text
            if discount and open_item is not None:
                amount = pence(discount[1])
                open_item.discounts.append(ParsedDiscount(
                    amount, discount_reason, line, discount_group,
                ))
                open_item.discount_pence += amount
            pending_text.clear()
            continue
        if discount and not QUANTITY_PRICE_DISCOUNT.fullmatch(line):
            if open_item is not None:
                amount = pence(discount[1])
                open_item.discounts.append(ParsedDiscount(
                    amount, marker_text or discount_reason, line, discount_group,
                ))
                open_item.discount_pence += amount
            pending_text.clear()
            continue
        weight_price = WEIGHT_PRICE.fullmatch(line)
        if weight_price and open_item is not None:
            open_item.quantity = float(weight_price[1].replace(',', '.'))
            open_item.unit_price_pence = pence(weight_price[2])
            continue
        quantity_discount = QUANTITY_PRICE_DISCOUNT.fullmatch(line)
        if quantity_discount and pending_text and orphan_original is not None:
            start_item(' '.join(pending_text), float(quantity_discount[1]),
                       pence(quantity_discount[2]), orphan_original)
            orphan_original = None
            pending_text = []
            if quantity_discount[3]:
                amount_value = pence(quantity_discount[3])
                open_item.discounts.append(ParsedDiscount(
                    amount_value, discount_reason, line, discount_group,
                ))
                open_item.discount_pence += amount_value
            continue
        if quantity_discount and open_item is not None:
            open_item.quantity = float(quantity_discount[1])
            open_item.unit_price_pence = pence(quantity_discount[2])
            if quantity_discount[3]:
                amount_value = pence(quantity_discount[3])
                open_item.discounts.append(ParsedDiscount(
                    amount_value, discount_reason, line, discount_group,
                ))
                open_item.discount_pence += amount_value
            continue
        quantity_price = QUANTITY_PRICE.fullmatch(line)
        if quantity_price:
            quantity = float(quantity_price[1])
            unit_price = pence(quantity_price[2])
            if pending_text:
                pending_quantity = quantity
                pending_unit_price = unit_price
            elif open_item is not None:
                open_item.quantity = quantity
                open_item.unit_price_pence = unit_price
            continue
        if re.fullmatch(r'\d+', line):
            if pending_text:
                pending_quantity = float(line)
            elif open_item is not None:
                open_item.quantity = float(line)
            continue
        printed_saving = PRINTED_SAVING.fullmatch(line)
        if printed_saving and open_item is not None:
            amount_value = pence(printed_saving[1])
            open_item.discounts.append(ParsedDiscount(
                amount_value, line[:printed_saving.start(1)].strip(), line,
                discount_group,
            ))
            open_item.discount_pence += amount_value
            continue
        each_price = EACH_PRICE.fullmatch(line)
        if each_price and open_item is not None:
            open_item.unit_price_pence = pence(each_price[1])
            continue
        amount = END_AMOUNT.search(line)
        if amount is None:
            if VOUCHER.search(line):
                pending_text.clear()
                continue
            if re.search(r'\b(?:GBP|EUR|USD)\b', line, re.I) or re.search(
                    r'\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b', line):
                pending_text.clear()
                continue
            if DISCOUNT_LABEL.search(line) and open_item is not None:
                discount_reason = line
                pending_text.clear()
                continue
            if split_product_line(line):
                quantity_name = LEADING_QUANTITY.match(line) if quantity_layout else None
                if quantity_name:
                    pending_quantity = float(quantity_name[1])
                    pending_text = [quantity_name[2]]
                elif quantity_layout and open_item is not None and not pending_text:
                    open_item.raw_description = f'{open_item.raw_description} {line}'.strip()
                elif pending_text and split_continuation(line):
                    pending_text.append(line)
                else:
                    pending_text = [line]
            continue
        prefix = line[:amount.start()].strip()
        if prefix and split_product_line(prefix):
            quantity_name = LEADING_QUANTITY.match(prefix) if quantity_layout else None
            if quantity_name:
                pending_quantity = float(quantity_name[1])
                pending_text = [quantity_name[2]]
            else:
                pending_text.append(prefix)
        value = pence(amount[1])
        if prefix and DISCOUNT_LABEL.search(prefix) and open_item is not None:
            discount_reason = prefix
            orphan_original = value
            pending_text = []
            continue
        if orphan_original is not None and prefix and split_product_line(prefix):
            embedded = EMBEDDED_WEIGHT_PRICE.fullmatch(prefix)
            if embedded:
                name = embedded[1]
                quantity = float(embedded[2].replace(',', '.'))
                unit_price = pence(embedded[3])
            else:
                name, quantity, unit_price = prefix, pending_quantity, pending_unit_price
            start_item(name, quantity, unit_price, orphan_original)
            orphan_original = value
            pending_text = []
            pending_quantity = 1.0
            pending_unit_price = None
            continue
        if not pending_text and open_item is not None and open_item.unit_price_pence is None:
            open_item.unit_price_pence = value
            continue
        if not pending_text and open_item is not None:
            orphan_original = value
            continue
        name = ' '.join(pending_text).strip()
        if not name or not split_product_line(name):
            continue
        start_item(name, pending_quantity, pending_unit_price, value)
        pending_text = []
        pending_quantity = 1.0
        pending_unit_price = None
    validate_open_item()
    return items, 0, warnings


def parse_receipt(text: str) -> ParsedReceipt:
    result = ParsedReceipt()
    text = re.sub(r'([£€$])\s*[OD](?=[.,]\d{2}\b)', r'\g<1>0', text, flags=re.I)
    lines = [normalise_currency_codes(re.sub(r'(?<![\w])f(?=\d+[.,]\d{2}\b)', '£', line.strip(), flags=re.I))
             for line in text.splitlines() if line.strip()]
    header = '\n'.join(lines[:8])
    matched_patterns = [pattern for pattern, _ in SUPERMARKETS if re.search(pattern, header, re.I)]
    stores = {name for pattern, name in SUPERMARKETS if re.search(pattern, header, re.I)}
    if len(stores) == 1:
        result.supermarket_name = stores.pop()
        result.supermarket_location = store_location(lines, matched_patterns)
    lines = normalise_bare_amounts(lines, result.supermarket_name)

    dates: set[str] = set()
    for match in re.finditer(r'\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})\b', text):
        if match[1]:
            year, month, day = map(int, match.group(1, 2, 3))
        else:
            day, month, year = map(int, match.group(4, 5, 6))
        add_date(dates, year, month, day)
    for match in re.finditer(
        rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s*[-/. ]\s*({MONTH_NAME})\s*[-/. ,]\s*(\d{{2}}|\d{{4}})\b',
        text, re.I,
    ):
        add_date(dates, int(match[3]), month_number(match[2]), int(match[1]))
    for match in re.finditer(
        rf'\b({MONTH_NAME})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,)?\s+(\d{{2}}|\d{{4}})\b',
        text, re.I,
    ):
        add_date(dates, int(match[3]), month_number(match[1]), int(match[2]))
    for match in re.finditer(
        rf'(?<!\d)(\d{{1,2}})\s*({COMPACT_MONTH_NAME})\s*(\d{{2}}|\d{{4}})(?!\d)',
        text, re.I,
    ):
        add_date(dates, int(match[3]), month_number(match[2]), int(match[1]))
    result.date_candidates = sorted(dates)
    if len(dates) == 1:
        result.purchase_date = next(iter(dates))
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
    total_discounts = set()
    receipt_discounts = set()
    summary_started = False
    for index, line in enumerate(lines):
        label = summary_text(line)
        amount = END_AMOUNT.search(line)
        if VOUCHER.search(label) and amount:
            receipt_discounts.add(pence(amount[1]))
            summary_started = True
            continue
        if TOTAL_DISCOUNT.search(label) and amount:
            total_discounts.add(pence(amount[1]))
            summary_started = True
            continue
        if TOTAL_DISCOUNT.search(label) and index + 1 < len(lines):
            following_amount = END_AMOUNT.fullmatch(lines[index + 1])
            if following_amount:
                total_discounts.add(pence(following_amount[1]))
                summary_started = True
                continue
        if is_total_label(label) and amount:
            totals.add(pence(amount[1]))
            summary_started = True
            continue
        if is_total_label(label) and index + 1 < len(lines):
            following_amount = END_AMOUNT.fullmatch(lines[index + 1])
            if following_amount:
                totals.add(pence(following_amount[1]))
                summary_started = True
                continue
        if SUMMARY.match(label):
            summary_started = True
            continue
    split_items, receipt_discount, item_warnings = parse_split_items(lines)
    result.items = split_items
    if len(receipt_discounts) == 1:
        result.receipt_discount_pence = next(iter(receipt_discounts))
    else:
        result.receipt_discount_pence = receipt_discount
    result.warnings.extend(item_warnings)



    if len(totals) == 1:
        result.total_pence = totals.pop()
    elif len(totals) > 1:
        result.warnings.append('Conflicting receipt totals found.')
    if len(total_discounts) == 1:
        result.total_discount_pence = total_discounts.pop()
    elif len(total_discounts) > 1:
        result.warnings.append('Conflicting total discount amounts found.')
    for key in ('supermarket_name', 'purchase_date', 'currency', 'total_pence'):
        if getattr(result, key) is None:
            result.warnings.append(f'{key} was not identified; manual review is required.')
    if not result.items:
        result.warnings.append('No grocery item lines identified.')
    elif result.total_pence is not None and (
        sum(item.original_pence - item.discount_pence for item in result.items)
        - result.receipt_discount_pence != result.total_pence
    ):
        result.warnings.append('Item totals do not match the receipt total; check discounts, taxes and missing lines.')
    return result
