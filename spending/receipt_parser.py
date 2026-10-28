"""Conservative, day-first English grocery receipt parsing for manual review."""

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from collections import Counter
import re

MONEY = r'(?<![\d.,])(?:[£€$]\s*)?(\d+[.,]\d{2})(?![\d.,])'
END_AMOUNT = re.compile(MONEY + r'\s*[A-Za-z]?\s*$')
TOTAL = re.compile(r'^(?:grand\s+total|total(?:\s+(?:due|to\s+pay))?|amount\s+due|balance\s+due)\s*:?\s*(?:(?:GBP|EUR|USD)\s*)?(?=[£€$\d])', re.I)
TOTAL_LABEL = re.compile(r'^(?:grand\s+total|total(?:\s+(?:due|to\s+pay))?|amount\s+due|balance\s+due)\s*:?$', re.I)
TOTAL_DISCOUNT = re.compile(r'^(?:total\s+(?:savings?|discounts?)|you\s+saved)\s*:?', re.I)
TOTAL_DISCOUNT_LABEL = re.compile(r'^(?:total\s+(?:savings?|discounts?)|you\s+saved)\s*:?$', re.I)
SUMMARY = re.compile(
    r'^(?:sub\s*total|total|grand total|amount due|balance due|cash(?:\s*back)?|'
    r'change|card|visa|mastercard|payment|vat|tax|tendered)\b', re.I,
)
NON_ITEM = re.compile(
    r'\b(?:savings?|discount|coupon|balance|loyalty|clubcard|nectar|points?|refund|'
    r'offers?|promotions?|member\s+(?:price|deal)|price\s*match|multi\s*buy)\b', re.I,
)
SPLIT_PRICE = re.compile(r'^[£€$]?\s*(\d+[.,]\d{2})\s*(?:[A-Z])?\s*$')
SPLIT_EACH_PRICE = re.compile(r'^[£€$]?\s*(\d+[.,]\d{2})\s+each\s*$', re.I)
SPLIT_DISCOUNT = re.compile(r'(?:^|\s)-\s*[£€$]?\s*(\d+[.,]\d{2})\s*$')
SPLIT_QUANTITY = re.compile(r'^(\d+(?:\.\d+)?)\s*(kg)?\s*[x×]\s*[£€$]?\s*(\d+[.,]\d{2})$', re.I)
LEADING_QUANTITY = re.compile(r'^(\d+(?:\.\d+)?)\s+(.+)$')
SPLIT_SUMMARY = re.compile(r'^(?:sub\s*total|total|grand\s+total)\b', re.I)
SUPERMARKETS = (
    (r'\bTESCO\b', 'Tesco'), (r"\bSAINSBURY(?:['’]?S)?\b", "Sainsbury's"),
    (r'\bALDI\b', 'Aldi'), (r'\bLIDL\b', 'Lidl'), (r'\bASDA\b', 'Asda'),
    (r'\bMORRISONS\b', 'Morrisons'), (r'\bWAITROSE\b', 'Waitrose'),
    (r'\bM\s*&\s*S\b|\bMARKS\s*(?:&|AND)\s*SPENCER\b', 'M&S'),
    (r'\bCO[ -]?OP\b', 'Co-op'), (r'\bICELAND\b', 'Iceland'),
    (r'\bOCADO\b', 'Ocado'),
)
STORE_FORMAT = re.compile(r'\b(?:extra|express|superstore|supermarket|local|metro|market)\b', re.I)
HEADER_METADATA = re.compile(r'\b(?:receipt|questions|visit|https?://|www\.|vat\s*(?:number)?|gb\d)\b', re.I)


@dataclass
class ParsedItem:
    raw_description: str
    quantity: float
    unit_price_pence: int | None
    original_pence: int
    discount_pence: int = 0


@dataclass
class ParsedReceipt:
    supermarket_name: str | None = None
    supermarket_location: str | None = None
    purchase_date: str | None = None
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
    """Accept a likely item description while excluding receipt metadata."""
    if (not re.search(r'[A-Za-z]', line) or re.fullmatch(r'[A-Z]{1,4}-?', line, re.I)
            or re.fullmatch(r'[x×*]', line, re.I)):
        return False
    if SUMMARY.match(line) or NON_ITEM.search(line) or SPLIT_PRICE.fullmatch(line):
        return False
    return not re.search(
        r'\b(?:receipt|not sales|questions|please visit|store-locator|vat number|'
        r'card|mastercard|authorisation|merchant|checkout|pan sequence|aid|'
        r'reduced to clear|cc\s+£|gb\d)\b',
        line, re.I,
    )


def split_continuation(line: str) -> bool:
    """Identify common wrapped description and pack-size rows."""
    return bool(re.match(
        r'^(?:\d+(?:\.\d+)?\s*(?:g|kg|ml|l)\b|flavou?r\b|toilet\b|pack\b|'
        r'blend\b|&\s*|and\b|d\s+)', line, re.I,
    ))


def parse_split_items(lines: list[str]) -> tuple[list[ParsedItem], int]:
    """Pair ordered product and price tokens without reusing an OCR position."""
    summary_index = next((index for index, line in enumerate(lines) if SPLIT_SUMMARY.match(line)), len(lines))
    drafts = []
    for index, line in enumerate(lines[:summary_index]):
        if SPLIT_PRICE.fullmatch(line) or SPLIT_EACH_PRICE.fullmatch(line) or SPLIT_DISCOUNT.search(line) or SPLIT_QUANTITY.fullmatch(line):
            continue
        if END_AMOUNT.search(line) or not split_product_line(line):
            continue
        quantity = LEADING_QUANTITY.fullmatch(line)
        has_price_since_previous_name = drafts and any(
            SPLIT_PRICE.fullmatch(previous) or SPLIT_EACH_PRICE.fullmatch(previous)
            for previous in lines[drafts[-1]['position'] + 1:index]
        )
        if drafts and (split_continuation(line) or (quantity is None and line[0].isupper()
                                                    and drafts[-1]['explicit_quantity']
                                                    and not has_price_since_previous_name)):
            drafts[-1]['raw_description'] = f"{drafts[-1]['raw_description']} {line}"
            continue
        quantity_value, description = (float(quantity[1]), quantity[2]) if quantity else (1.0, line)
        drafts.append({
            'raw_description': description,
            'quantity': quantity_value,
            'unit_price_pence': None,
            'discount_pence': 0,
            'discount_position': None,
            'original_pence': None,
            'position': index,
            'quantity_position': None,
            'price_position': None,
            'explicit_quantity': quantity is not None,
        })

    for index, line in enumerate(lines[:summary_index]):
        quantity = SPLIT_QUANTITY.fullmatch(line)
        if quantity:
            nearby = [
                draft for draft in drafts
                if 0 < index - draft['position'] <= 3
            ]
            if nearby:
                candidate = max(nearby, key=lambda draft: draft['position'])
                candidate['quantity'] = float(quantity[1])
                candidate['unit_price_pence'] = pence(quantity[3])
                candidate['quantity_position'] = index

    prices = [
        (index, pence(price[1]))
        for index, line in enumerate(lines[:summary_index])
        if (price := SPLIT_PRICE.fullmatch(line))
    ]
    discounts = [
        (index, pence(discount[1]))
        for index, line in enumerate(lines[:summary_index])
        if (discount := SPLIT_DISCOUNT.search(line))
    ]
    after_discount_positions = set()
    after_discount_owner = {}
    for discount_index, discount_amount in discounts:
        preceding = [price for price in prices
                     if price[0] < discount_index and price[0] not in after_discount_positions]
        following = next((price for price in prices if price[0] > discount_index), None)

        # Some receipts print original, reduced, then discount. The reduced
        # amount is used to confirm the relationship but is not an item price.
        if len(preceding) >= 2:
            original, reduced = preceding[-2], preceding[-1]
            if discount_index - reduced[0] <= 4 and original[1] - discount_amount == reduced[1]:
                after_discount_positions.add(reduced[0])
                after_discount_owner[reduced[0]] = original[0]
                continue

        # Others print original, discount, then reduced. Apply the same check.
        if preceding and following:
            original = preceding[-1]
            if following[0] - discount_index <= 4 and original[1] - discount_amount == following[1]:
                after_discount_positions.add(following[0])
                after_discount_owner[following[0]] = original[0]

    # Product descriptions and their base prices retain independent OCR order.
    # Pair the first unused price with the first item, then mark that position
    # as consumed. Equal amounts at later positions remain separate tokens.
    base_prices = [price for price in prices if price[0] not in after_discount_positions]
    item_drafts = drafts
    if base_prices and drafts:
        first_price_position = base_prices[0][0]
        drafts_before_price = [draft for draft in drafts if draft['position'] < first_price_position]
        strong_before_price = [draft for draft in drafts_before_price
                               if draft['explicit_quantity'] or draft['quantity_position'] is not None]
        first_item = (strong_before_price[0] if strong_before_price else
                      (drafts_before_price[-1] if drafts_before_price else drafts[0]))
        start = drafts.index(first_item)
        item_drafts = drafts[start:]

        # A stray OCR word can sit between numbered products in a column-style
        # header block. Do not let it consume a price token before the first
        # price column begins.
        strong_positions = [draft['position'] for draft in item_drafts
                            if draft['position'] < first_price_position
                            and (draft['explicit_quantity'] or draft['quantity_position'] is not None)]
        if len(strong_positions) >= 2:
            item_drafts = [draft for draft in item_drafts
                           if not (draft['position'] < first_price_position
                                   and strong_positions[0] < draft['position'] < strong_positions[-1]
                                   and not draft['explicit_quantity']
                                   and draft['quantity_position'] is None)]

    used_price_positions = set()
    for draft, (price_index, amount) in zip(item_drafts, base_prices):
        if price_index in used_price_positions:
            continue
        draft['original_pence'] = amount
        draft['price_position'] = price_index
        used_price_positions.add(price_index)

    priced = {draft['price_position']: draft for draft in drafts if draft['price_position'] is not None}
    for index, line in enumerate(lines[:summary_index]):
        each_price = SPLIT_EACH_PRICE.fullmatch(line)
        if each_price:
            earlier = [draft for draft in drafts if draft['price_position'] is not None and draft['price_position'] < index]
            if earlier:
                earlier[-1]['unit_price_pence'] = pence(each_price[1])
            continue
        discount = SPLIT_DISCOUNT.search(line)
        if discount:
            nearest_amount = next(
                (position for position in range(index - 1, -1, -1) if SPLIT_PRICE.fullmatch(lines[position])),
                None,
            )
            # Do not let a discount jump over an OCR amount that could not be
            # paired with a product. It must remain for manual review instead.
            owner_position = after_discount_owner.get(nearest_amount, nearest_amount)
            if owner_position is None or owner_position not in priced:
                continue
            previous = owner_position
            if (previous is not None
                    and priced[previous]['discount_position'] is None
                    and not NON_ITEM.search(priced[previous]['raw_description'])):
                # Keep the exact value from one OCR token. Arithmetic may help
                # choose its item, but must never combine or manufacture a
                # value for an OCR-backed field.
                priced[previous]['discount_pence'] = pence(discount[1])
                priced[previous]['discount_position'] = index

    receipt_discount = 0
    for index, line in enumerate(lines):
        if re.match(r'^coupons?\s*/?\s*vouchers?\s*:?', line, re.I):
            for following in lines[index + 1:index + 3]:
                discount = SPLIT_DISCOUNT.search(following)
                if discount:
                    receipt_discount = pence(discount[1])
                    break
    items = [
        ParsedItem(draft['raw_description'], draft['quantity'], draft['unit_price_pence'],
                   draft['original_pence'], draft['discount_pence'])
        for draft in drafts
        if draft['original_pence'] is not None and not NON_ITEM.search(draft['raw_description'])
    ]
    return items, receipt_discount


def parse_receipt(text: str) -> ParsedReceipt:
    result = ParsedReceipt()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    header = '\n'.join(lines[:8])
    matched_patterns = [pattern for pattern, _ in SUPERMARKETS if re.search(pattern, header, re.I)]
    stores = {name for pattern, name in SUPERMARKETS if re.search(pattern, header, re.I)}
    if len(stores) == 1:
        result.supermarket_name = stores.pop()
        result.supermarket_location = store_location(lines, matched_patterns)

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
    total_discounts = set()
    summary_started = False
    for index, line in enumerate(lines):
        amount = END_AMOUNT.search(line)
        if TOTAL_DISCOUNT.match(line) and amount:
            total_discounts.add(pence(amount[1]))
            summary_started = True
            continue
        if TOTAL_DISCOUNT_LABEL.fullmatch(line) and index + 1 < len(lines):
            following_amount = END_AMOUNT.fullmatch(lines[index + 1])
            if following_amount:
                total_discounts.add(pence(following_amount[1]))
                summary_started = True
                continue
        if TOTAL.match(line) and amount:
            totals.add(pence(amount[1]))
            summary_started = True
            continue
        if TOTAL_LABEL.fullmatch(line) and index + 1 < len(lines):
            following_amount = END_AMOUNT.fullmatch(lines[index + 1])
            if following_amount:
                totals.add(pence(following_amount[1]))
                summary_started = True
                continue
        if SUMMARY.match(line):
            summary_started = True
            continue
        if not amount:
            continue
        prefix = line[:amount.start()].strip()
        # A payment/change section is outside the purchased items. In
        # particular, negative cashback amounts must not become promotions.
        if summary_started:
            continue
        if NON_ITEM.search(line) or prefix.endswith('-'):
            result.warnings.append(f'Adjustment/discount requires review: {line}')
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
            unit_price = pence(re.sub(r'[£€$\s]', '', unit_text))
        elif leading:
            quantity = Decimal(leading[1])
            prefix = leading[2]
        if quantity <= 0:
            result.warnings.append(f'Invalid quantity requires review: {line}')
            continue
        total = pence(amount[1])
        if unit_price is not None and Decimal(unit_price) * quantity != total:
            result.warnings.append(f'Quantity and unit price do not match line total: {line}')
        result.items.append(ParsedItem(prefix, float(quantity), unit_price, total))

    split_items, receipt_discount = parse_split_items(lines)
    if split_items:
        result.items = split_items
        result.receipt_discount_pence = receipt_discount
        handled_discounts = Counter(item.discount_pence for item in split_items if item.discount_pence)
        if receipt_discount:
            handled_discounts[receipt_discount] += 1
        promotion_total = sum(item.discount_pence for item in split_items)
        remaining_warnings = []
        for warning in result.warnings:
            if not warning.startswith('Adjustment/discount requires review: '):
                remaining_warnings.append(warning)
                continue
            discount = SPLIT_DISCOUNT.search(warning.rsplit(': ', 1)[1])
            if discount is None:
                remaining_warnings.append(warning)
                continue
            amount = pence(discount[1])
            if handled_discounts[amount]:
                handled_discounts[amount] -= 1
            elif amount != promotion_total:
                remaining_warnings.append(warning)
        result.warnings = remaining_warnings



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
