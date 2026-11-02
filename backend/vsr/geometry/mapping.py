"""Layer / style meaning vocabulary and the default name heuristics used by the mapping wizard."""
import re

MEANINGS = ["hull_shell", "deck", "frame_line", "block_boundary", "opening", "obstruction", "frame_text",
            "centreline", "baseline", "dimension", "ignore"]

_HEUR = [
    (r"(HULL|SHELL|PLATE|SKIN|BORDAJ|INVELIS)", "hull_shell"),
    (r"(^|[_\-\s])(CL|C\.L|CENT(RE|ER)L)", "centreline"),
    (r"(^|[_\-\s])(BL|BASE)", "baseline"),
    (r"(FR(AME)?[_\-\s]?(NO|NUM|TXT|TEXT))|(^FRNO)", "frame_text"),
    (r"(DECK|PUNTE)", "deck"),
    (r"(BLOCK|BLOC)[_\-\s]?(B(OUND)?|LIM)", "block_boundary"),
    (r"(OPEN|HOLE|GAUR)", "opening"),
    (r"(PIPE|CABLE|TRAY|DUCT|OUTFIT|EQUIP|OBST|KEEL[_\-\s]?BLOCK)", "obstruction"),
    (r"(DIM|COTA)", "dimension"),
    (r"(FRAME|^FR$|^FR[_\-])", "frame_line"),
]


def guess_meaning(name: str) -> str:
    n = name.upper()
    for rx, meaning in _HEUR:
        if re.search(rx, n):
            return meaning
    return "ignore"


FRAME_RX = re.compile(r"\bFR(?:AME)?\.?\s*(-?\d+(?:\.\d+)?)", re.I)


def parse_frame(text: str):
    m = FRAME_RX.search(text or "")
    return float(m.group(1)) if m else None
