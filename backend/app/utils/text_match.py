"""İşletme adı benzerliği - harici (OSM) ve kullanıcı kayıtlarının aynı yer olup olmadığını
değerlendirirken konum yakınlığına EK sinyal (bkz. service_point_service.merge)."""
import re
import unicodedata
from difflib import SequenceMatcher

# Ayırt edici olmayan tür sözcükleri - "Deniz Balık Restaurant" ile "Deniz Balık" aynı yer.
_GENERIC_WORDS = {
    "restoran", "restaurant", "restorani", "lokanta", "lokantasi", "kafe", "cafe", "cafesi", "kafesi",
    "balik", "baligi", "et", "kebap", "kebab", "kebapcisi", "ocakbasi", "mangal", "evi", "salonu",
    "hastane", "hastanesi", "devlet", "saglik", "ocagi", "merkezi", "aile", "asm", "tip", "wc", "tuvalet",
    "dus", "the", "ve", "and",
}
_TR_MAP = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "ç": "c", "Ç": "c",
                         "ö": "o", "Ö": "o", "ü": "u", "Ü": "u"})


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name.translate(_TR_MAP).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w and w not in _GENERIC_WORDS]
    return " ".join(words)


def names_match(a: str | None, b: str | None, threshold: float = 0.72) -> bool | None:
    """True/False: iki ad aynı işletmeyi mi gösteriyor. None: karar verilemez (biri adsız
    veya ad yalnızca genel sözcüklerden ibaret) - çağıran taraf yalnızca konuma güvenir."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return None
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold
