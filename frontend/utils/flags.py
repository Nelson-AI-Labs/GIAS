# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Flags — single source of truth for flag emoji and language-code resolution.

Country flags are *generated*, not stored: a flag emoji is two Unicode Regional
Indicator Symbols derived from the ISO 3166-1 alpha-2 code (chr(0x1F1E6 + offset)).
A regional-indicator pair is byte-for-byte identical to the literal flag (🇳🇱 ==
country_code_to_flag("NL")), so generation costs no rendering quality.

Languages are not algorithmically mappable to flags (a language is not a country),
so language names + inferred countries come from the authoritative ISO 639 / CLDR
data via the `langcodes` library — no hand-maintained language table to drift.
Languages with no single country (Esperanto, Latin, ...) fall back to the globe.
"""

from functools import lru_cache
from typing import Dict, Optional

import langcodes
from langcodes.tag_parser import LanguageTagError

GLOBE = "🌐"


def country_code_to_flag(alpha2: Optional[str]) -> str:
    """ISO 3166-1 alpha-2 code -> flag emoji, or globe when not a valid code."""
    code = (alpha2 or "").strip().upper()
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        return GLOBE
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


# Country name / non-ISO variant (lowercased) -> ISO alpha-2 code.
# Plain 2-letter ISO codes are resolved directly and need no entry here.
_COUNTRY_ALIASES: Dict[str, str] = {
    'afghanistan': 'AF', 'albania': 'AL', 'algeria': 'DZ', 'america': 'US',
    'american samoa': 'AS', 'andorra': 'AD', 'angola': 'AO', 'antarctica': 'AQ',
    'argentina': 'AR', 'australia': 'AU', 'austria': 'AT', 'bahamas': 'BS',
    'bahrain': 'BH', 'bangladesh': 'BD', 'barbados': 'BB', 'belarus': 'BY',
    'belgium': 'BE', 'belgië': 'BE', 'belize': 'BZ', 'benin': 'BJ',
    'bhutan': 'BT', 'bolivia': 'BO', 'bosnia': 'BA', 'bosnia and herzegovina': 'BA',
    'botswana': 'BW', 'bouvet island': 'BV', 'brasil': 'BR', 'brazil': 'BR',
    'british indian ocean territory': 'IO', 'brunei': 'BN', 'bulgaria': 'BG', 'burkina faso': 'BF',
    'burma': 'MM', 'burundi': 'BI', 'cambodia': 'KH', 'cameroon': 'CM',
    'canada': 'CA', 'cape verde': 'CV', 'central african republic': 'CF', 'chad': 'TD',
    'chile': 'CL', 'china': 'CN', 'colombia': 'CO', 'comoros': 'KM',
    'congo': 'CG', 'cook islands': 'CK', 'costa rica': 'CR', 'croatia': 'HR',
    'cuba': 'CU', 'cyprus': 'CY', 'czech republic': 'CZ', 'czechia': 'CZ',
    "côte d'ivoire": 'CI', 'danmark': 'DK', 'democratic republic of congo': 'CD', 'denmark': 'DK',
    'deutschland': 'DE', 'djibouti': 'DJ', 'dominican republic': 'DO', 'drc': 'CD',
    'east timor': 'TL', 'ecuador': 'EC', 'eesti': 'EE', 'egypt': 'EG',
    'el salvador': 'SV', 'equatorial guinea': 'GQ', 'eritrea': 'ER', 'españa': 'ES',
    'estonia': 'EE', 'eswatini': 'SZ', 'ethiopia': 'ET', 'falkland islands': 'FK',
    'faroe islands': 'FO', 'fiji': 'FJ', 'finland': 'FI', 'france': 'FR',
    'french guiana': 'GF', 'french polynesia': 'PF', 'french southern territories': 'TF', 'gabon': 'GA',
    'gambia': 'GM', 'germany': 'DE', 'ghana': 'GH', 'great britain': 'GB',
    'greece': 'GR', 'greenland': 'GL', 'guam': 'GU', 'guatemala': 'GT',
    'guinea': 'GN', 'guinea-bissau': 'GW', 'guyana': 'GY', 'haiti': 'HT',
    'heard island': 'HM', 'holland': 'NL', 'honduras': 'HN', 'hong kong': 'HK',
    'hrvatska': 'HR', 'hungary': 'HU', 'iceland': 'IS', 'india': 'IN',
    'indonesia': 'ID', 'iran': 'IR', 'iraq': 'IQ', 'ireland': 'IE',
    'israel': 'IL', 'italia': 'IT', 'italy': 'IT', 'ivory coast': 'CI',
    'jamaica': 'JM', 'japan': 'JP', 'jordan': 'JO', 'kazakhstan': 'KZ',
    'kenya': 'KE', 'kiribati': 'KI', 'korea': 'KR', 'kosovo': 'XK',
    'kuwait': 'KW', 'kyrgyzstan': 'KG', 'laos': 'LA', 'latvia': 'LV',
    'latvija': 'LV', 'lebanon': 'LB', 'lesotho': 'LS', 'liberia': 'LR',
    'libya': 'LY', 'liechtenstein': 'LI', 'lietuva': 'LT', 'lithuania': 'LT',
    'luxembourg': 'LU', 'macao': 'MO', 'macau': 'MO', 'macedonia': 'MK',
    'madagascar': 'MG', 'magyarország': 'HU', 'malawi': 'MW', 'malaysia': 'MY',
    'maldives': 'MV', 'mali': 'ML', 'malta': 'MT', 'marshall islands': 'MH',
    'mauritania': 'MR', 'mauritius': 'MU', 'mayotte': 'YT', 'mexico': 'MX',
    'micronesia': 'FM', 'moldova': 'MD', 'monaco': 'MC', 'mongolia': 'MN',
    'montenegro': 'ME', 'morocco': 'MA', 'mozambique': 'MZ', 'myanmar': 'MM',
    'méxico': 'MX', 'namibia': 'NA', 'nauru': 'NR', 'nepal': 'NP',
    'netherlands': 'NL', 'new caledonia': 'NC', 'new zealand': 'NZ', 'nicaragua': 'NI',
    'niger': 'NE', 'nigeria': 'NG', 'niue': 'NU', 'norge': 'NO',
    'north korea': 'KP', 'north macedonia': 'MK', 'northern mariana islands': 'MP', 'norway': 'NO',
    'oman': 'OM', 'pakistan': 'PK', 'palau': 'PW', 'palestine': 'PS',
    'panama': 'PA', 'papua new guinea': 'PG', 'paraguay': 'PY', 'peru': 'PE',
    'perú': 'PE', 'philippines': 'PH', 'poland': 'PL', 'polska': 'PL',
    'portugal': 'PT', 'puerto rico': 'PR', 'qatar': 'QA', 'republic of congo': 'CG',
    'reunion': 'RE', 'romania': 'RO', 'românia': 'RO', 'russia': 'RU',
    'rwanda': 'RW', 'réunion': 'RE', 'samoa': 'WS', 'san marino': 'SM',
    'sao tome and principe': 'ST', 'saudi arabia': 'SA', 'schweiz': 'CH', 'senegal': 'SN',
    'serbia': 'RS', 'seychelles': 'SC', 'sierra leone': 'SL', 'singapore': 'SG',
    'slovakia': 'SK', 'slovenia': 'SI', 'slovenija': 'SI', 'slovensko': 'SK',
    'solomon islands': 'SB', 'somalia': 'SO', 'south africa': 'ZA', 'south georgia': 'GS',
    'south korea': 'KR', 'south sudan': 'SS', 'spain': 'ES', 'srbija': 'RS',
    'sri lanka': 'LK', 'sudan': 'SD', 'suomi': 'FI', 'suriname': 'SR',
    'svalbard': 'SJ', 'sverige': 'SE', 'swaziland': 'SZ', 'sweden': 'SE',
    'switzerland': 'CH', 'syria': 'SY', 'taiwan': 'TW', 'tajikistan': 'TJ',
    'tanzania': 'TZ', 'thailand': 'TH', 'timor-leste': 'TL', 'togo': 'TG',
    'tokelau': 'TK', 'tonga': 'TO', 'trinidad and tobago': 'TT', 'tunisia': 'TN',
    'turkey': 'TR', 'turkmenistan': 'TM', 'tuvalu': 'TV', 'türkiye': 'TR',
    'uae': 'AE', 'uganda': 'UG', 'uk': 'GB', 'ukraine': 'UA',
    'united arab emirates': 'AE', 'united kingdom': 'GB', 'united states': 'US', 'uruguay': 'UY',
    'usa': 'US', 'uzbekistan': 'UZ', 'vanuatu': 'VU', 'vatican': 'VA',
    'vatican city': 'VA', 'venezuela': 'VE', 'vietnam': 'VN', 'yemen': 'YE',
    'zambia': 'ZM', 'zimbabwe': 'ZW', 'éire': 'IE', 'ísland': 'IS',
    'österreich': 'AT', 'ελλάδα': 'GR', 'беларусь': 'BY', 'българия': 'BG',
    'россия': 'RU', 'україна': 'UA', '中国': 'CN', '日本': 'JP',
}


# Language resolution uses the authoritative ISO 639 / CLDR data via `langcodes`,
# so any valid ISO 639 code or English name resolves to a canonical name and an
# inferred country for the flag — no hand-maintained language table to fall behind.
# CLDR maximization picks the most-populous region (en->US, pt->BR);
# _FLAG_REGION_OVERRIDES restores the European defaults this tool expects.
_FLAG_REGION_OVERRIDES: Dict[str, str] = {
    "en": "GB", "pt": "PT", "es": "ES",
}


@lru_cache(maxsize=1024)
def _resolve_language(value: str):
    """Resolve an ISO 639 code or English name to a langcodes.Language, or None."""
    text = (value or "").strip()
    if not text:
        return None
    # Codes/tags parse via get(); names ("English") raise and fall through to find().
    try:
        lang = langcodes.Language.get(text)
        if lang.is_valid() and lang.language:
            return lang
    except LanguageTagError:
        pass
    try:
        lang = langcodes.find(text)
    except LookupError:
        return None
    return lang if lang.is_valid() else None


@lru_cache(maxsize=512)
def country_code_to_name(alpha2: Optional[str]) -> str:
    """ISO 3166-1 alpha-2 code -> English country name (via CLDR), or the code
    itself when it can't be resolved."""
    code = (alpha2 or "").strip().upper()
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        return (alpha2 or "").strip()
    try:
        name = langcodes.Language.get("und-" + code).territory_name("en")
        return name or code
    except Exception:
        return code


def get_country_flag(country_name_or_code: Optional[str]) -> str:
    """Flag emoji for a country name or ISO code; globe if unresolved."""
    key = (country_name_or_code or "").strip().lower()
    if not key:
        return GLOBE
    if key in _COUNTRY_ALIASES:
        return country_code_to_flag(_COUNTRY_ALIASES[key])
    if len(key) == 2 and key.isascii() and key.isalpha():
        return country_code_to_flag(key)
    return GLOBE


def language_to_region(language_code: Optional[str]) -> Optional[str]:
    """ISO 3166-1 alpha-2 region for a language code/name (e.g. 'spa'->'ES',
    'en'->'GB'), or None when the language maps to no single country."""
    lang = _resolve_language(language_code or "")
    if lang is None:
        return None
    region = _FLAG_REGION_OVERRIDES.get(lang.language)
    if region is None:
        try:
            region = lang.maximize().territory
        except Exception:
            region = None
    return region


def get_language_flag(language_code: Optional[str]) -> str:
    """Flag emoji for a language code or name; globe if unmapped/countryless."""
    return country_code_to_flag(language_to_region(language_code))


def normalize_language_name(language: Optional[str]) -> Optional[str]:
    """
    Canonical English name for a language code/name (e.g. "deu"/"German" -> "German",
    "slk" -> "Slovak"). Returns None for missing/blank/unrecognised input, which
    callers treat as "unclassified".
    """
    lang = _resolve_language(language or "")
    return lang.display_name("en") if lang is not None else None


def is_supported_language(language_code: Optional[str]) -> bool:
    """True if the value resolves to a known ISO 639 language."""
    return _resolve_language(language_code or "") is not None
