"""Generate the Phase 0 synthetic dataset for SIH26122 (P2E Bridge).

Deterministic: the same SEED always yields byte-identical files. Stdlib only.

    python scripts/phase0/generate_dataset.py              # writes data/synthetic/
    python scripts/phase0/generate_dataset.py --out DIR    # writes elsewhere (the validator uses this)

Flow: catalog (objects -> L5/L6 activities with planned dates) -> hidden "truth"
timeline (actual dates, holds, spool/cable/ring sub-items) -> field sources (daily
progress reports, discipline spreadsheets) written from the truth with realistic
terminology drift -> ground truth (labels, expected extraction, truth events).
See data/synthetic/README.md for the file contract.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import xlsx_min

SEED = 26122
GENERATOR_VERSION = "1.0.0"
PROJECT_CODE = "CGS-EXP-01"
PROJECT_NAME = "Crude Oil Gathering Station Expansion (synthetic)"
DATA_DATE = date(2026, 8, 31)      # schedule status date: actuals up to here are already in the PMIS
WINDOW_START = date(2026, 9, 1)    # first field-report day
N_REPORT_DAYS = 14                 # Monday-Saturday site calendar

# Intended mix of labelled items (fraction ranges); the validator enforces these.
TARGET_MIX = {"matched": (0.60, 0.85), "ambiguous": (0.08, 0.25), "unmatched": (0.05, 0.20)}
MIN_ITEMS = 250
MIN_PER_HARD_CASE = 10
LEAF_RANGE = (300, 350)

ONE = timedelta(days=1)
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "synthetic"


def rng_for(*parts) -> random.Random:
    """Independent, stable RNG per purpose: changing one section never reshuffles another."""
    return random.Random(":".join(str(p) for p in (SEED, *parts)))


def td(n: int) -> timedelta:
    return timedelta(days=n)


def workday(d: date) -> date:
    return d + ONE if d.weekday() == 6 else d   # no Sunday work/reporting


def workdays(a: date, b: date) -> list[date]:
    return [a + td(i) for i in range((b - a).days + 1) if (a + td(i)).weekday() != 6]


def _report_days() -> list[date]:
    days, d = [], WINDOW_START
    while len(days) < N_REPORT_DAYS:
        if d.weekday() != 6:
            days.append(d)
        d += ONE
    return days


RDAYS = _report_days()
WINDOW_END = RDAYS[-1]
RDAY_IDX = {d: i for i, d in enumerate(RDAYS)}


def in_window(d: date | None) -> bool:
    return d is not None and d in RDAY_IDX


def next_rday(d: date, k: int = 1) -> date | None:
    i = RDAY_IDX[d] + k
    return RDAYS[i] if i < len(RDAYS) else None


MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def fmt_date(d: date, kind: str) -> str:
    """Locale-independent date formats seen in Indian site paperwork."""
    return {
        "dmy_slash": f"{d.day:02d}/{d.month:02d}/{d.year}",
        "dmy2_slash": f"{d.day:02d}/{d.month:02d}/{d.year % 100:02d}",
        "dmy_dot": f"{d.day:02d}.{d.month:02d}.{d.year}",
        "dmy2_dot": f"{d.day:02d}.{d.month:02d}.{d.year % 100:02d}",
        "d_mon_y2": f"{d.day:02d}-{MON[d.month - 1]}-{d.year % 100:02d}",
        "mon_d_y": f"{MON[d.month - 1]} {d.day}, {d.year}",
        "iso": d.isoformat(),
        "ordinal": f"{_ordinal(d.day)} {'Sept' if d.month == 9 else MON[d.month - 1]} {d.year}",
        "dm_slash": f"{d.day}/{d.month}",
        "d_mon": f"{d.day}-{MON[d.month - 1]}",
    }[kind]


HEADER_DATE_FMTS = ["dmy_slash", "d_mon_y2", "mon_d_y", "dmy_dot", "iso", "ordinal"]
INLINE_DATE_FMTS = ["dm_slash", "dmy2_dot", "d_mon", "dmy2_slash"]
SHEET_DATE_FMTS = ["dmy2_slash", "d_mon", "dmy_dot"]

# --------------------------------------------------------------------------- catalog

AREAS = {"A1": "Inlet Manifold & Separation", "A2": "Electrical Substation",
         "A3": "Process Pipe Rack & Pump House", "A4": "Tank Farm & Utilities"}
DISCIPLINES = {"CIV": "civil", "PIP": "piping", "SEQ": "static_eq", "ROT": "rotating_eq",
               "ELE": "electrical", "INS": "instrumentation", "HSE": "hse"}
DISC_TITLE = {"CIV": "Civil & Structural", "PIP": "Piping", "SEQ": "Static Equipment", "ROT": "Rotating Equipment",
              "ELE": "Electrical", "INS": "Instrumentation", "HSE": "HSE & Fire Protection"}
GROUPS = {  # one daily progress report (DPR) per group per report day
    "civil": dict(discs=["CIV"], code="CIV", title="Civil", contractor="M/s Synthetic Civil Constructions", informal=0.5),
    "piping": dict(discs=["PIP"], code="PIP", title="Piping", contractor="M/s Synthetic Piping Works", informal=0.25),
    "mechanical": dict(discs=["SEQ", "ROT"], code="MEC", title="Mechanical (Static & Rotating)", contractor="M/s Synthetic Mech Erectors", informal=0.25),
    "electrical": dict(discs=["ELE"], code="ELE", title="Electrical", contractor="M/s Synthetic Electricals", informal=0.3),
    "instrumentation": dict(discs=["INS"], code="INS", title="Instrumentation", contractor="M/s Synthetic Instrumentation Services", informal=0.25),
    "hse": dict(discs=["HSE"], code="HSE", title="HSE & Fire Protection", contractor="M/s Synthetic Fire & Safety", informal=0.5),
}
DISC_GROUP = {d: g for g, v in GROUPS.items() for d in v["discs"]}
# Reporting gaps: these DPRs were never submitted (events roll to the next report).
MISSING_DPRS = {("instrumentation", RDAYS[7]), ("hse", RDAYS[3]), ("hse", RDAYS[10])}


def P(formal, abbrev, synonym, hinglish, partial="", tag_only=""):
    sp = lambda s: [x for x in s.split("|") if x]
    return {"formal": sp(formal), "abbrev": sp(abbrev), "synonym": sp(synonym), "hinglish": sp(hinglish),
            "partial": sp(partial), "tag_only": sp(tag_only)}


@dataclass
class Step:
    key: str
    code: str
    plan: str      # planned activity name template
    atype: str     # activity type code (as in a P6 activity-code field)
    unit: str | None
    ph: dict       # field phrasings by style; {id} = object identifier, {desc} = tagless description


STEPS = {s.key: s for s in [
    # civil: equipment foundations
    Step("fdn_exc", "EXC", "Excavation for foundation {tag}", "Excavation", None,
         P("Excavation for foundation {id}|Excavation of {id} foundation", "Excvn {id} fdn|Exc. for {id} fdn",
           "Digging for {id} foundation|Earthwork for {id} fdn pit", "{id} fdn ki khudai|{id} foundation khudai",
           "excavation for {desc} foundation")),
    Step("fdn_pcc", "PCC", "PCC for foundation {tag}", "PCC", None,
         P("PCC for foundation {id}", "PCC {id} fdn|pcc @ {id}", "Lean concrete below {id} foundation|Blinding concrete for {id}",
           "{id} PCC dhalai", "PCC for {desc} foundation")),
    Step("fdn_reb", "REB", "Reinforcement & shuttering foundation {tag}", "Reinforcement", None,
         P("Reinforcement & shuttering for foundation {id}", "Rebar & shutt. {id} fdn|R/F & S/F {id}",
           "Steel binding and formwork at {id} foundation|Bar bending & fixing for {id} fdn", "{id} fdn sariya bandhai",
           "shuttering for {desc} foundation")),
    Step("fdn_rcc", "RCC", "RCC concreting foundation {tag}", "Concreting", "cum",
         P("RCC concreting of foundation {id}", "RCC {id} fdn|Concreting {id} fdn", "Casting of {id} foundation|Concrete pour for {id} fdn",
           "{id} foundation ki dhalai", "casting of {desc} foundation")),
    Step("fdn_bf", "BKF", "Backfilling around foundation {tag}", "Backfilling", None,
         P("Backfilling around foundation {id}", "B/F {id} fdn|Backfill {id}", "Soil filling & compaction around {id} fdn",
           "{id} fdn bharai", "backfilling around {desc} foundation")),
    # civil: pipe racks, substation, trenches, drains
    Step("pr_ftg", "FTG", "Excavation & PCC for pipe rack {tag} footings", "Excavation", None,
         P("Excavation & PCC for pipe rack {id} footings", "Exc & PCC {id} ftgs", "Footing excavation at pipe rack {id}",
           "{id} footing khudai", "pipe rack footing excavation")),
    Step("pr_ped", "PED", "RCC footings & pedestals pipe rack {tag}", "Concreting", None,
         P("RCC footings & pedestals for pipe rack {id}", "RCC ftgs/pedestals {id}", "Pedestal casting at pipe rack {id}",
           "{id} pedestal dhalai", "pipe rack pedestal casting")),
    Step("pr_stl", "STL", "Structural steel erection pipe rack {tag}", "Steel erection", None,
         P("Structural steel erection of pipe rack {id}", "Str. steel erec {id}|{id} str steel", "Erection of rack steel for {id}",
           "{id} steel erection ka kaam", "pipe rack steel erection")),
    Step("sub_plinth", "PLN", "Substation building – plinth beam", "Concreting", None,
         P("Plinth beam of {id}", "Plinth bm {id}", "Plinth beam casting at {id}", "{id} plinth beam dhalai", "plinth beam casting")),
    Step("sub_col", "COL", "Substation building – column casting", "Concreting", None,
         P("Column casting of {id}", "Col. casting {id}", "Column concreting for {id}", "{id} column dhalai", "column casting")),
    Step("sub_roof", "ROF", "Substation building – roof slab", "Concreting", None,
         P("Roof slab of {id}", "Roof slab {id}", "Roof slab casting at {id}", "{id} chhat ki dhalai", "roof slab casting")),
    Step("sub_brick", "BRK", "Substation building – brickwork", "Masonry", None,
         P("Brickwork of {id}", "Brkwk {id}", "Masonry walls of {id}", "{id} eent ka kaam", "brickwork")),
    Step("sub_plaster", "PLS", "Substation building – plastering", "Finishing", None,
         P("Plastering of {id}", "Plaster {id}", "Internal & external plaster at {id}", "{id} plaster ka kaam", "plastering")),
    Step("ct_exc", "EXC", "Cable trench excavation – {name}", "Excavation", None,
         P("Excavation of {id}", "Exc. {id}", "Digging of {id}", "{id} khudai", "cable trench excavation")),
    Step("ct_wall", "WAL", "Cable trench PCC & walls – {name}", "Concreting", None,
         P("PCC & walls of {id}", "PCC+wall {id}", "Trench wall casting {id}", "{id} wall dhalai", "cable trench walls")),
    Step("swd", "SWD", "Storm water drain – {aname}", "Drainage", None,
         P("Storm water drain {id}", "SWD {id}", "Surface drain construction {id}", "{id} naali ka kaam", "storm water drain")),
    # piping
    Step("pip_erect", "ERC", "Erect piping line {tag}", "Erection", "spools",
         P("Erection of line {id}|Piping erection line {id}", "Erec {id}|{id} erctn", "Spool erection {id}|Pipe laying on rack for {id}",
           "{id} line ka erection|{id} spool fitting", "erection of {desc}")),
    Step("pip_weld", "WLD", "Welding & NDT line {tag}", "Welding", None,
         P("Welding & NDT of line {id}", "Wldg/NDT {id}|{id} welding+RT", "Joint welding and radiography {id}|Weld joints & X-ray for {id}",
           "{id} welding ka kaam", "welding of {desc}")),
    Step("pip_ht", "HT", "Hydrotest line {tag} ({tp})", "Hydrotest", None,
         P("Hydrotest of line {id}", "HT {id}|Hydro {id}", "Pressure testing of {id}|Hydro testing {id}", "{id} ka hydrotest",
           "hydrotest of {desc}", tag_only="{tp}|Test pack {tp}")),
    Step("pip_rein", "RST", "Reinstatement line {tag}", "Reinstatement", None,
         P("Reinstatement of line {id}", "Reinst. {id}|{id} reinstmt", "Box-up after hydrotest {id}|Blind removal & reinstatement {id}",
           "{id} reinstatement ka kaam", "reinstatement of {desc}")),
    Step("ps_fab", "FAB", "Fabrication of pipe supports – {tag}", "Fabrication", None,
         P("Fabrication of pipe supports for {id}", "Supp. fab {id}|PS fab {id}", "Shoe & guide fabrication for {id}",
           "{id} support banana", "pipe support fabrication")),
    Step("ps_erect", "PSE", "Erection of pipe supports – {tag}", "Erection", None,
         P("Erection of pipe supports at {id}", "Supp. erec {id}|PS erctn {id}", "Fixing of shoes & guides at {id}",
           "{id} support fitting", "pipe support erection")),
    # static equipment
    Step("eq_recv", "RCV", "Receipt & inspection {tag}", "Receipt", None,
         P("Receipt & inspection of {id}", "Rcpt/insp {id}", "Unloading and inspection of {id}", "{id} site pe receive",
           "receipt of {desc}")),
    Step("eq_erect", "ERC", "Erection of {desc} {tag} on foundation", "Erection", None,
         P("Erection of {id} on foundation", "{id} erctn on fdn|Set {id}", "Lifting & placing of {id}|{id} placement with crane",
           "{id} ko foundation pe rakhna", "{desc} erection|lifting of {desc}")),
    Step("eq_grout", "GRT", "Alignment & grouting {tag}", "Grouting", None,
         P("Alignment & grouting of {id}", "Algn & grtg {id}|{id} grouting", "Levelling and grout pour {id}", "{id} grouting ka kaam",
           "grouting of {desc}")),
    Step("eq_int", "INT", "Installation of internals {tag}", "Internals", None,
         P("Installation of internals in {id}", "Internals {id}", "Fixing trays & demister in {id}|{id} internals fit-up",
           "{id} internals fitting", "{desc} internals")),
    Step("eq_boxup", "BOX", "Final box-up {tag}", "Box-up", None,
         P("Final box-up of {id}", "Box-up {id}", "Manway closing for {id}", "{id} box-up", "box-up of {desc}")),
    Step("tk_bottom", "BTM", "Annular & bottom plate laying {tag}", "Plate laying", None,
         P("Bottom plate laying {id}", "Btm plates {id}", "Annular plate & bottom welding {id}", "{id} bottom plate bichhana",
           "{desc} bottom plates")),
    Step("tk_shell1", "SH1", "Shell erection courses 1–3 {tag}", "Shell erection", "rings",
         P("Shell erection courses 1-3 of {id}", "Shell crs 1-3 {id}", "{id} shell plates lower rings", "{id} shell neeche ke course",
           "{desc} shell lower courses")),
    Step("tk_shell2", "SH2", "Shell erection courses 4–6 {tag}", "Shell erection", "rings",
         P("Shell erection courses 4-6 of {id}", "Shell crs 4-6 {id}", "{id} shell plates upper rings", "{id} shell upar ke course",
           "{desc} shell upper courses")),
    Step("tk_roof", "ROF", "Roof structure & sheeting {tag}", "Roof erection", None,
         P("Roof structure & sheeting of {id}", "Roof str. {id}", "Roof rafters and sheeting {id}", "{id} roof ka kaam", "{desc} roof")),
    Step("tk_ht", "HT", "Tank hydrotest {tag}", "Hydrotest", None,
         P("Hydrotest of tank {id}", "HT {id}|Water fill test {id}", "Water filling test of {id}", "{id} tank hydrotest",
           "{desc} hydrotest")),
    # rotating equipment
    Step("pmp_set", "SET", "Setting of {desc} {tag} on foundation", "Erection", None,
         P("Setting of pump {id} on foundation", "{id} set on fdn|Pump {id} placement", "{id} pump positioned on base",
           "{id} pump ko base pe rakhna", "{desc} placement")),
    Step("pmp_grout", "GRT", "Grouting pump {tag}", "Grouting", None,
         P("Grouting of pump {id}", "{id} grtg|Grout {id}", "Base plate grouting {id}", "{id} ka grouting", "grouting of {desc}")),
    Step("pmp_align", "ALN", "Final alignment pump {tag}", "Alignment", None,
         P("Final alignment of pump {id}", "Final algn {id}", "Laser alignment pump-motor {id}|Coupling alignment {id}",
           "{id} alignment", "{desc} alignment")),
    Step("pmp_solo", "SOL", "Motor solo run {tag}", "Testing", None,
         P("Motor solo run of {id}", "Solo run {id}", "Decoupled motor trial {id}|No-load run motor {id}", "{id} motor trial",
           "{desc} motor trial")),
    Step("cmp_skid", "SKD", "Setting of compressor skid {tag}", "Erection", None,
         P("Setting of compressor skid {id}", "{id} skid set", "Skid placement for {id}", "{id} skid rakhna", "{desc} skid setting")),
    Step("cmp_grout", "GRT", "Grouting compressor skid {tag}", "Grouting", None,
         P("Grouting of {id} skid", "{id} grtg", "Epoxy grouting of {id} skid", "{id} skid grouting", "{desc} grouting")),
    Step("cmp_lube", "LUB", "Lube oil flushing {tag}", "Flushing", None,
         P("Lube oil flushing of {id}", "LO flushing {id}", "Oil flushing of {id} lube system", "{id} oil flushing",
           "{desc} lube oil flushing")),
    Step("cmp_align", "ALN", "Alignment compressor-driver {tag}", "Alignment", None,
         P("Alignment of {id} with driver", "{id} algn", "Coupling alignment {id}", "{id} alignment", "{desc} alignment")),
    Step("cmp_run", "RUN", "Mechanical run test {tag}", "Testing", None,
         P("Mechanical run test of {id}", "MRT {id}", "Trial run of {id}", "{id} trial run", "{desc} trial run")),
    # electrical
    Step("tr_place", "PLC", "Placement of transformer {tag} on plinth", "Erection", None,
         P("Placement of transformer {id}", "Trafo {id} placement", "Shifting & positioning {id} on plinth",
           "{id} transformer plinth pe", "transformer placement")),
    Step("pnl_inst", "INS", "Installation of {desc} {tag}", "Installation", None,
         P("Installation of {id}", "{id} instln|{id} erection", "Erection of {id} panel|{id} panel positioning & levelling",
           "{id} panel fitting", "{desc} installation")),
    Step("cbl_pull", "CBL", "Cable pulling – {name}", "Cable pulling", "m",
         P("Cable pulling for {id}", "Cbl pulling {id}|{id} cable laying", "Laying of power cables for {id}|Cable laying {id}",
           "{id} cable khinchai", "power cable laying")),
    Step("cbl_term", "TRM", "Glanding & termination – {name}", "Termination", "cables",
         P("Glanding & termination for {id}", "Termn {id}|G&T {id}", "Cable termination work {id}|Lugging & glanding {id}",
           "{id} termination ka kaam", "cable termination")),
    Step("irt", "IRT", "IR testing of cables – {name}", "Testing", None,
         P("IR testing of cables for {id}", "IR test {id}", "Megger testing {id} cables", "{id} megger", "cable IR testing")),
    Step("earth", "ERT", "Earthing – earth pits & grid, {aname}", "Earthing", None,
         P("Earth pits & earthing grid in {id}", "EP & grid {id}|Earthing {id}", "Earth pit installation {id}", "{id} earthing ka kaam",
           "earthing work")),
    Step("tray", "TRY", "Cable tray erection, {aname}", "Erection", None,
         P("Cable tray erection in {id}", "Tray erec {id}|C/T {id}", "Cable tray fixing {id}", "{id} tray lagana", "cable tray erection")),
    Step("light", "LGT", "Area lighting poles & fixtures, {aname}", "Installation", None,
         P("Lighting poles & fixtures in {id}", "Ltg poles {id}", "Street light pole erection {id}", "{id} light pole lagana",
           "lighting poles")),
    # instrumentation
    Step("ins_inst", "INS", "Installation of {desc} {tag}", "Installation", None,
         P("Installation of {id}", "{id} instln|{id} mtd", "Mounting of {id} on stand|{id} stand fixing & mounting",
           "{id} lagana", "{desc} mounting")),
    Step("ins_tube", "TUB", "Impulse tubing {tag}", "Tubing", None,
         P("Impulse tubing for {id}", "Tubing {id}|IT {id}", "SS tubing hook-up {id}", "{id} tubing ka kaam", "{desc} tubing")),
    Step("ins_loop", "LCK", "Loop check {tag}", "Loop check", None,
         P("Loop checking of {id}", "Loop chk {id}", "Loop test {id}", "{id} loop check", "{desc} loop check")),
    Step("jb_inst", "INS", "Installation of junction box {tag}", "Installation", None,
         P("Installation of junction box {id}", "{id} fixing|{id} instln", "Mounting {id} on support", "{id} fixing ka kaam",
           "junction box fixing", tag_only="{id}")),
    Step("icbl", "ICB", "Instrument cable laying, {aname}", "Cable pulling", None,
         P("Instrument cable laying in {id}", "Inst. cbl {id}", "Signal cable pulling {id}", "{id} instrument cable khinchai",
           "instrument cable laying")),
    Step("dcs", "DCS", "Installation of DCS cabinets in CCR", "Installation", None,
         P("Installation of {id}", "{id} instln", "Positioning {id} in control room", "{id} fitting", "{desc} installation")),
    Step("mc_inst", "INS", "Installation of marshalling cabinet {tag}", "Installation", None,
         P("Installation of marshalling cabinet {id}", "{id} instln", "Marshalling panel {id} positioning", "{id} fitting",
           "{desc} installation", tag_only="{id}")),
    # HSE & fire protection
    Step("gd_inst", "INS", "Installation of gas detector {tag}", "Installation", None,
         P("Installation of gas detector {id}", "{id} instln|{id} fixing", "Mounting of {id} detector head", "{id} lagana",
           "gas detector mounting", tag_only="{id}")),
    Step("hyd", "HYD", "Fire hydrants & monitors, {aname}", "Installation", None,
         P("Fire hydrants & monitors in {id}", "Hydrants {id}", "Hydrant & monitor erection {id}", "{id} hydrant lagana",
           "fire hydrant erection")),
    Step("ss_inst", "INS", "Installation of safety shower & eyewash {tag}", "Installation", None,
         P("Installation of safety shower {id}", "{id} instln", "Safety shower & eye wash fixing {id}", "{id} shower lagana",
           "safety shower fixing", tag_only="{id}")),
    Step("fap", "INS", "Installation of fire alarm panel {tag}", "Installation", None,
         P("Installation of fire alarm panel {id}", "{id} instln", "Mounting fire alarm panel {id}", "{id} panel lagana",
           "{desc} installation", tag_only="{id}")),
    Step("ws", "INS", "Windsock installation {tag}", "Installation", None,
         P("Windsock installation {id}", "{id} instln", "Wind sock mast erection {id}", "{id} lagana", "{desc} installation",
           tag_only="{id}")),
    Step("fg_loop", "FGL", "F&G system loop check, {aname}", "Loop check", None,
         P("F&G loop check in {id}", "F&G LC {id}", "Fire & gas loop testing {id}", "{id} F&G loop check", "F&G loop check")),
]}
SUB_ITEM_STEPS = {"pip_erect", "tk_shell1", "tk_shell2", "cbl_pull", "cbl_term"}


@dataclass
class Act:
    id: str
    obj: "Obj"
    step: str
    name: str
    level: int
    ps: date
    pf: date
    preds: list[tuple[str, str, int]] = field(default_factory=list)   # (pred_id, FS|SS, lag days)
    qty: float | None = None
    as_: date | None = None
    af: date | None = None
    hold: tuple | None = None          # (hold_date, resume_date|None, category, reason)
    sub: list[tuple[str, date]] = field(default_factory=list)          # (sub-item id, truth date)
    daily: dict = field(default_factory=dict)                         # date -> qty done that day


@dataclass
class Obj:
    key: str
    disc: str
    area: str
    tag: str
    name: str
    desc: str | None
    ids: dict
    canon: list[str]
    chain: list[tuple]
    start: date
    area_in_id: bool = False
    summary: str | None = None
    after: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    acts: list[Act] = field(default_factory=list)


def tag_ids(tag: str, *syn: str) -> dict:
    return {"formal": [tag], "abbrev": [tag.replace("-", ""), tag], "synonym": [tag, *syn], "hinglish": [tag]}


def area_ids(a: str) -> dict:
    n = a[1]
    return {"formal": [f"Area-{n}"], "abbrev": [f"A{n}", f"A-{n}"], "synonym": [f"area {n}"], "hinglish": [f"area {n}"]}


def line_ids(size: int, svc: str, num: str, spec: str) -> dict:
    return {"formal": [f'{size}"-{svc}-{num}-{spec}'], "abbrev": [f"L-{num}", f"L{num}", f"{svc}-{num}"],
            "synonym": [f"line {num}", f"{size} inch line {num}", f"{num} line"], "hinglish": [num]}


def between(r: random.Random, a: date, b: date) -> date:
    return a + td(r.randint(0, (b - a).days))


FDN_EQUIP = [("P-101A", "A3", "crude transfer pump"), ("P-101B", "A3", "crude transfer pump"),
             ("P-102A", "A3", "produced water pump"), ("P-102B", "A3", "produced water pump"),
             ("P-201A", "A4", "fire water pump"), ("P-201B", "A4", "fire water pump"),
             ("K-301", "A1", "gas compressor"), ("V-101", "A1", "inlet separator"), ("V-102", "A1", "test separator"),
             ("V-103", "A1", "gas scrubber"), ("E-101", "A3", "crude heat exchanger"),
             ("T-401", "A4", "crude storage tank"), ("T-402", "A4", "crude storage tank")]
LINES = [("A1", 24, "P", "1101", "A1A", "crude inlet header"), ("A1", 18, "P", "1102", "A1A", "separator outlet line"),
         ("A1", 12, "G", "1103", "B1A", "gas line"), ("A1", 8, "P", "1104", "A1A", "test separator line"),
         ("A1", 6, "W", "1105", "A1A", "produced water line"),
         ("A3", 24, "P", "1201", "A1A", "crude header"), ("A3", 24, "P", "1203", "A1A", "crude header"),
         ("A3", 18, "P", "1205", "A1A", "pump suction line"), ("A3", 16, "P", "1207", "A1A", "pump discharge line"),
         ("A3", 16, "P", "1211", "A1A", "pump discharge line"), ("A3", 12, "P", "1213", "A1A", "heater bypass line"),
         ("A3", 10, "W", "1215", "A1A", "produced water line"), ("A3", 8, "P", "1217", "A1A", "recirculation line"),
         ("A4", 20, "P", "1401", "A1A", "tank inlet line"), ("A4", 16, "P", "1403", "A1A", "tank outlet line"),
         ("A4", 10, "W", "1405", "A1A", "tank drain line"), ("A4", 8, "F", "1407", "F1A", "fire water ring main")]
INSTRUMENTS = [("FT-1101", "A1"), ("PT-1102", "A1"), ("LT-1103", "A1"), ("PT-1104", "A1"), ("TT-1105", "A1"),
               ("FT-2031", "A3"), ("PT-2041", "A3"), ("PT-2042", "A3"), ("TT-2051", "A3"), ("FT-2033", "A3"),
               ("LT-4011", "A4"), ("LT-4012", "A4"), ("TT-4013", "A4")]
INSTR_DESC = {"FT": "flow transmitter", "PT": "pressure transmitter", "LT": "level transmitter", "TT": "temperature transmitter"}
CABLE_GROUPS = [  # key, area, name, ids, canon, loads
    ("MCC1", "A2", "MCC-1 outgoing feeders",
     {"formal": ["MCC-1 outgoing feeders"], "abbrev": ["MCC-1", "MCC1 fdrs"], "synonym": ["MCC-1 feeder cables"], "hinglish": ["MCC-1"]},
     ["MCC-1"], "MCC-1", ["P-101A-M", "P-101B-M", "P-102A-M", "P-102B-M", "K-301-AUX", "E-101-HTR"]),
    ("MCC2", "A2", "MCC-2 incomer & feeders",
     {"formal": ["MCC-2 incomer & feeders"], "abbrev": ["MCC-2", "MCC2 fdrs"], "synonym": ["MCC-2 cables"], "hinglish": ["MCC-2"]},
     ["MCC-2"], "MCC-2", ["P-201A-M", "P-201B-M", "PCC-1", "LDB-A4-01", "LDB-A4-02"]),
    ("LVA1", "A1", "LV power cables Area-1",
     {"formal": ["Area-1 LV power cables"], "abbrev": ["A1 LV cbls", "LV A-1"], "synonym": ["LV cables area 1"], "hinglish": ["area 1 LV"]},
     [], "PCC-1", ["LDB-A1-01", "LDB-A1-02", "JB-101", "JB-102"]),
    ("LVA3", "A3", "LV power cables Area-3",
     {"formal": ["Area-3 LV power cables"], "abbrev": ["A3 LV cbls", "LV A-3"], "synonym": ["LV cables area 3"], "hinglish": ["area 3 LV"]},
     [], "PCC-1", ["LDB-A3-01", "LDB-A3-02", "LDB-A3-03", "JB-301", "JB-302"]),
    ("LVA4", "A4", "LV power cables Area-4",
     {"formal": ["Area-4 LV power cables"], "abbrev": ["A4 LV cbls", "LV A-4"], "synonym": ["LV cables area 4"], "hinglish": ["area 4 LV"]},
     [], "PCC-1", ["LDB-A4-01", "LDB-A4-02", "JB-401"]),
    ("HTTR1", "A2", "11 kV HT cable to TR-1",
     {"formal": ["11 kV HT cable to TR-1"], "abbrev": ["HT cbl TR-1", "HT TR1"], "synonym": ["HT cable for TR-1"], "hinglish": ["TR-1 HT"]},
     ["TR-1"], "HT-SWBD-1", ["TR-1"]),
    ("HTTR2", "A2", "11 kV HT cable to TR-2",
     {"formal": ["11 kV HT cable to TR-2"], "abbrev": ["HT cbl TR-2", "HT TR2"], "synonym": ["HT cable for TR-2"], "hinglish": ["TR-2 HT"]},
     ["TR-2"], "HT-SWBD-1", ["TR-2"]),
]
CABLE_SIZES = ["3Cx95 sqmm", "3.5Cx185 sqmm", "4Cx16 sqmm", "3Cx240 sqmm", "4Cx6 sqmm"]


def build_catalog() -> list[Obj]:
    """Objects in dependency order, each planned immediately (later objects reference earlier activities)."""
    objs: list[Obj] = []

    def add(o: Obj) -> Obj:
        plan_obj(o)
        objs.append(o)
        return o

    R = lambda *k: rng_for("plan", *k)
    fdn: dict[str, Obj] = {}
    fdn_chain = [("fdn_exc", 3, None), ("fdn_pcc", 1, ("FS", 0)), ("fdn_reb", 4, ("FS", 1)), ("fdn_rcc", 2, ("FS", 0)), ("fdn_bf", 3, ("FS", 7))]
    for tag, area, desc in FDN_EQUIP:
        r = R("fdn", tag)
        if tag.startswith("T-"):
            start = between(r, date(2026, 7, 6), date(2026, 7, 12))
        elif tag.endswith("B") and tag[:-1] + "A" in fdn:
            start = fdn[tag[:-1] + "A"].start + td(r.randint(0, 2))   # sibling pumps run in parallel
        else:
            start = between(r, date(2026, 7, 20), date(2026, 9, 8))
        o = add(Obj(tag.replace("-", ""), "CIV", area, tag, f"Foundation {tag} ({desc})", desc, tag_ids(tag), [tag], fdn_chain, start))
        o.acts[3].qty = r.choice(range(18, 62, 2))
        fdn[tag] = o
    for n, area in [(1, "A1"), (2, "A3"), (3, "A3"), (4, "A4")]:
        tag = f"PR-{n}"
        add(Obj(f"PR{n}", "CIV", area, tag, f"Pipe rack {tag}", "pipe rack", tag_ids(tag, f"pipe rack {n}"), [tag],
                [("pr_ftg", 6, None), ("pr_ped", 8, ("FS", 1)), ("pr_stl", 10, ("FS", 5))],
                between(R("pr", n), date(2026, 7, 13), date(2026, 8, 20))))
    add(Obj("SSB", "CIV", "A2", "substation building", "Substation building", "substation building",
            {"formal": ["substation building"], "abbrev": ["S/S bldg", "SS bldg"], "synonym": ["sub-station building"],
             "hinglish": ["substation building"]}, [],
            [("sub_plinth", 8, None), ("sub_col", 8, ("FS", 1)), ("sub_roof", 10, ("FS", 2)), ("sub_brick", 10, ("FS", 1)), ("sub_plaster", 8, ("FS", 0))],
            between(R("ssb"), date(2026, 7, 13), date(2026, 7, 20))))
    for k, side in [("CTN", "north"), ("CTS", "south")]:
        tag = f"CT-{side[0].upper()}"
        add(Obj(k, "CIV", "A2", tag, f"Cable trench ({side})", "cable trench",
                {"formal": [f"cable trench ({side})"], "abbrev": [tag], "synonym": [f"{side} cable trench"], "hinglish": [f"{side} cable trench"]},
                [tag], [("ct_exc", 6, None), ("ct_wall", 8, ("FS", 1))], between(R("ct", k), date(2026, 8, 20), date(2026, 9, 5))))
    for area in ["A3", "A4"]:
        add(Obj(f"SWD{area[1]}", "CIV", area, f"Area-{area[1]}", f"Storm water drain Area-{area[1]}", "storm water drain",
                area_ids(area), [], [("swd", 12, None)], between(R("swd", area), date(2026, 8, 25), date(2026, 9, 10)), area_in_id=True))

    for i, (area, size, svc, num, spec, ldesc) in enumerate(LINES):
        r = R("line", num)
        spools = r.randint(4, 12)
        erect = math.ceil(spools * 1.5)
        tag = f'{size}"-{svc}-{num}-{spec}'
        o = Obj(num, "PIP", area, tag, f"Line {tag}", f'{size}" {ldesc}', line_ids(size, svc, num, spec), [f"LINE-{num}"],
                [("pip_erect", erect, None), ("pip_weld", erect + 3, ("SS", 2)), ("pip_ht", 2, ("FS", 3)), ("pip_rein", 2, ("FS", 1))],
                between(r, date(2026, 8, 15), date(2026, 9, 22)), extra={"spools": spools, "tp": f"TP-{11 + i:03d}", "num": num})
        add(o)
        o.acts[0].qty = spools
    for n, area in [(1, "A1"), (2, "A3"), (3, "A3"), (4, "A4")]:
        tag = f"PR-{n}"
        add(Obj(f"PS{n}", "PIP", area, f"pipe rack {tag}", f"Pipe supports {tag}", "pipe rack",
                {"formal": [f"pipe rack {tag}"], "abbrev": [tag, f"PR{n}"], "synonym": [f"rack {n}"], "hinglish": [tag]}, [tag],
                [("ps_fab", 10, None), ("ps_erect", 12, ("FS", 2))], between(R("ps", n), date(2026, 8, 1), date(2026, 8, 28))))

    for tag, area, desc in [("V-101", "A1", "inlet separator"), ("V-102", "A1", "test separator"), ("V-103", "A1", "gas scrubber"),
                            ("E-101", "A3", "crude heat exchanger")]:
        chain = [("eq_recv", 1, None), ("eq_erect", 2, ("FS", 3)), ("eq_grout", 3, ("FS", 2))]
        chain += [("eq_int", 6, ("FS", 3))] if tag.startswith("V") else []
        chain += [("eq_boxup", 1, ("FS", 8))]
        add(Obj(tag.replace("-", ""), "SEQ", area, tag, f"{tag} {desc.title()}", desc, tag_ids(tag), [tag], chain,
                between(R("eq", tag), date(2026, 8, 10), date(2026, 9, 5)), after={1: (fdn[tag].acts[3], 10)}))
    for tag in ["T-401", "T-402"]:
        add(Obj(tag.replace("-", ""), "SEQ", "A4", tag, f"{tag} Crude Storage Tank", "crude storage tank", tag_ids(tag, f"tank {tag[2:]}"), [tag],
                [("tk_bottom", 10, None), ("tk_shell1", 15, ("FS", 1)), ("tk_shell2", 15, ("FS", 1)), ("tk_roof", 12, ("FS", 2)), ("tk_ht", 7, ("FS", 5))],
                between(R("tk", tag), date(2026, 7, 27), date(2026, 8, 10)), summary=f"Mechanical erection {tag}",
                after={0: (fdn[tag].acts[4], 2)}))
    for tag, area, desc in [x for x in FDN_EQUIP if x[0].startswith("P-")]:
        add(Obj(tag.replace("-", ""), "ROT", area, tag, f"{tag} {desc.title()}", desc, tag_ids(tag), [tag],
                [("pmp_set", 1, None), ("pmp_grout", 1, ("FS", 2)), ("pmp_align", 2, ("FS", 20)), ("pmp_solo", 1, ("FS", 3))],
                between(R("pmp", tag), date(2026, 8, 20), date(2026, 9, 10)), after={0: (fdn[tag].acts[3], 10)}))
    add(Obj("K301", "ROT", "A1", "K-301", "K-301 Gas Compressor Package", "gas compressor", tag_ids("K-301", "compressor K-301"), ["K-301"],
            [("cmp_skid", 2, None), ("cmp_grout", 2, ("FS", 2)), ("cmp_lube", 7, ("FS", 10)), ("cmp_align", 3, ("FS", 2)), ("cmp_run", 2, ("FS", 5))],
            date(2026, 8, 20), summary="Install gas compressor package K-301", after={0: (fdn["K-301"].acts[3], 10)}))

    for tag, desc in [("TR-1", "transformer"), ("TR-2", "transformer")]:
        add(Obj(tag.replace("-", ""), "ELE", "A2", tag, f"Transformer {tag}", desc, tag_ids(tag), [tag], [("tr_place", 2, None)],
                between(R("tr", tag), date(2026, 8, 24), date(2026, 9, 12))))
    for tag, desc in [("HT-SWBD-1", "HT switchboard"), ("MCC-1", "MCC panel"), ("MCC-2", "MCC panel"), ("PCC-1", "PCC panel")]:
        add(Obj(tag.replace("-", ""), "ELE", "A2", tag, f"{desc.upper() if desc.startswith(('MCC', 'PCC')) else desc.title()} {tag}",
                desc, tag_ids(tag), [tag], [("pnl_inst", 3, None)], between(R("pnl", tag), date(2026, 8, 20), date(2026, 9, 10))))
    for key, area, name, ids, canon, src, loads in CABLE_GROUPS:
        r = R("cbl", key)
        cables, total, i = [], 0, 1
        target = 350 if key.startswith("HT") else r.choice(range(1200, 2300, 100))
        while total < target:
            ln = r.choice(range(20, 160, 5)) if not key.startswith("HT") else r.choice(range(150, 200, 5))
            cables.append((f"C-{key}-{i:03d}", src, r.choice(loads), r.choice(CABLE_SIZES[:2] if key.startswith("HT") else CABLE_SIZES), ln))
            total, i = total + ln, i + 1
        pull = r.randint(14, 20)
        chain = [("cbl_pull", pull, None), ("cbl_term", pull + 5, ("SS", 5))] + ([("irt", 2, ("FS", 2))] if key.startswith("MCC") else [])
        o = add(Obj(f"C{key}", "ELE", area, name, name, "power cable", ids, canon, chain, between(r, date(2026, 8, 28), date(2026, 9, 12)),
                    area_in_id=not canon, extra={"cables": cables}))
        o.acts[0].qty, o.acts[1].qty = total, len(cables)
    for step, k, lo, hi, desc in [("earth", "ERT", date(2026, 8, 10), date(2026, 9, 8), "earthing"),
                                  ("tray", "TRY", date(2026, 8, 12), date(2026, 9, 5), "cable tray"),
                                  ("light", "LGT", date(2026, 9, 12), date(2026, 10, 10), "area lighting")]:
        for area in AREAS:
            dur = {"earth": 12, "tray": 15, "light": 10}[step]
            add(Obj(f"{k}{area[1]}", "ELE", area, f"Area-{area[1]}", f"{desc.title()} Area-{area[1]}", desc, area_ids(area), [],
                    [(step, dur, None)], between(R(step, area), lo, hi), area_in_id=True))

    for tag, area in INSTRUMENTS:
        kind, num = tag.split("-")
        desc = INSTR_DESC[kind]
        chain = [("ins_inst", 2, None)] + ([("ins_tube", 3, ("FS", 2))] if kind != "TT" else []) + [("ins_loop", 1, ("FS", 25))]
        ids = {"formal": [tag], "abbrev": [tag.replace("-", ""), tag.replace("-", " ")], "synonym": [f"{desc} {num}"], "hinglish": [tag]}
        add(Obj(tag.replace("-", ""), "INS", area, tag, f"{tag} {desc.title()}", desc, ids, [tag], chain,
                between(R("ins", tag), date(2026, 8, 26), date(2026, 9, 18))))
    for tag, area in [("JB-101", "A1"), ("JB-102", "A1"), ("JB-301", "A3"), ("JB-302", "A3"), ("JB-303", "A3"), ("JB-304", "A3"), ("JB-401", "A4")]:
        add(Obj(tag.replace("-", ""), "INS", area, tag, f"Junction box {tag}", "junction box", tag_ids(tag, f"junction box {tag[3:]}"), [tag],
                [("jb_inst", 2, None)], between(R("jb", tag), date(2026, 8, 24), date(2026, 9, 15))))
    for area in ["A1", "A3", "A4"]:
        add(Obj(f"ICB{area[1]}", "INS", area, f"Area-{area[1]}", f"Instrument cables Area-{area[1]}", "instrument cable", area_ids(area), [],
                [("icbl", 12, None)], between(R("icbl", area), date(2026, 8, 30), date(2026, 9, 18)), area_in_id=True))
    add(Obj("DCS", "INS", "A2", "DCS cabinets", "DCS cabinets (CCR)", "DCS cabinet",
            {"formal": ["DCS cabinets"], "abbrev": ["DCS cab."], "synonym": ["DCS panels in CCR"], "hinglish": ["DCS panel"]}, ["DCS"],
            [("dcs", 5, None)], between(R("dcs"), date(2026, 8, 25), date(2026, 9, 2))))
    add(Obj("MC1", "INS", "A2", "MC-1", "Marshalling cabinet MC-1", "marshalling cabinet", tag_ids("MC-1"), ["MC-1"],
            [("mc_inst", 3, None)], between(R("mc"), date(2026, 8, 28), date(2026, 9, 8))))

    for tag, area in [("GD-101", "A1"), ("GD-102", "A1"), ("GD-301", "A3"), ("GD-302", "A3")]:
        add(Obj(tag.replace("-", ""), "HSE", area, tag, f"Gas detector {tag}", "gas detector", tag_ids(tag, f"gas detector {tag[3:]}"), [tag],
                [("gd_inst", 1, None)], between(R("gd", tag), date(2026, 9, 1), date(2026, 9, 25))))
    for area in ["A1", "A3", "A4"]:
        add(Obj(f"HYD{area[1]}", "HSE", area, f"Area-{area[1]}", f"Fire hydrants Area-{area[1]}", "fire hydrant", area_ids(area), [],
                [("hyd", 10, None)], between(R("hyd", area), date(2026, 8, 25), date(2026, 9, 15)), area_in_id=True))
    for tag, area in [("SS-101", "A1"), ("SS-301", "A3")]:
        add(Obj(tag.replace("-", ""), "HSE", area, tag, f"Safety shower {tag}", "safety shower", tag_ids(tag, f"safety shower {tag[3:]}"), [tag],
                [("ss_inst", 2, None)], between(R("ss", tag), date(2026, 9, 1), date(2026, 9, 20))))
    add(Obj("FAP1", "HSE", "A2", "FAP-1", "Fire alarm panel FAP-1", "fire alarm panel", tag_ids("FAP-1"), ["FAP-1"], [("fap", 2, None)],
            between(R("fap"), date(2026, 9, 1), date(2026, 9, 10))))
    add(Obj("WS1", "HSE", "A1", "WS-1", "Windsock WS-1", "windsock", tag_ids("WS-1"), ["WS-1"], [("ws", 1, None)],
            between(R("ws"), date(2026, 9, 1), date(2026, 9, 15))))
    for area in ["A1", "A3"]:
        add(Obj(f"FGL{area[1]}", "HSE", area, f"Area-{area[1]}", f"F&G loop check Area-{area[1]}", "F&G loop", area_ids(area), [],
                [("fg_loop", 5, None)], between(R("fgl", area), date(2026, 10, 5), date(2026, 10, 20)), area_in_id=True))
    return objs


def plan_obj(o: Obj) -> None:
    prev = None
    for i, (sk, dur, link) in enumerate(o.chain):
        st = STEPS[sk]
        ps = o.start if prev is None else (prev.pf + td(1 + link[1]) if link[0] == "FS" else prev.ps + td(link[1]))
        preds = [] if prev is None else [(prev.id, link[0], link[1])]
        if i in o.after:
            a, gap = o.after[i]
            ps = max(ps, a.pf + td(1 + gap))
            preds.append((a.id, "FS", gap))
        name = st.plan.format(tag=o.tag, name=o.name, desc=o.desc, tp=o.extra.get("tp", ""), aname=f"Area-{o.area[1]}")
        act = Act(f"{o.disc}-{o.area}-{o.key}-{st.code}", o, sk, name, 6 if o.summary else 5, ps, ps + td(dur - 1), preds)
        o.acts.append(act)
        prev = act


# --------------------------------------------------------------------------- truth timeline

SLIPS = [-2, -1, 0, 0, 0, 1, 2, 3, 4, 6, 9]
HOLD_REASONS = {
    "material": sorted({"gaskets not received", "bolts short supply", "spools not delivered from fab shop", "cement shortage",
                        "rebar not received", "anchor bolts not received", "shims not received", "cable drums not received",
                        "glands short supply", "SS tubing short supply", "transmitters not received", "detector heads not received"}),
    "manpower": ["welders shortage", "fitters diverted to other area"],
    "weather": ["heavy rain", "waterlogging after rain"],
    "permit": ["hot work permit pending", "excavation permit awaited"],
    "design": ["drawing revision awaited", "clash with cable tray, RFI raised"],
    "equipment": ["crane breakdown", "DG set failure"],
}
MATERIAL_BY_DISC = {  # material shortages are discipline-specific
    "CIV": ["cement shortage", "rebar not received"], "PIP": ["gaskets not received", "spools not delivered from fab shop", "bolts short supply"],
    "SEQ": ["anchor bolts not received"], "ROT": ["shims not received"], "ELE": ["cable drums not received", "glands short supply"],
    "INS": ["SS tubing short supply", "transmitters not received"], "HSE": ["detector heads not received"],
}
HOLD_CATS = {"CIV": ["material", "weather", "permit", "equipment"], "PIP": ["material", "manpower", "permit", "design"],
             "SEQ": ["equipment", "weather", "manpower"], "ROT": ["equipment", "design", "manpower"],
             "ELE": ["material", "design", "manpower"], "INS": ["material", "design"], "HSE": ["material", "permit"]}


def spread(r: random.Random, days: list[date], n: int) -> list[date]:
    """n sorted dates over days; first and last day always used (they define actual start/finish)."""
    if n == 1:
        return [days[0]]
    mid = sorted(r.choice(days) for _ in range(n - 2))
    return [days[0], *mid, days[-1]]


def build_truth(objs: list[Obj]) -> None:
    for o in objs:
        r = rng_for("truth", o.disc, o.key)
        cum = r.choice(SLIPS)
        prev = None
        for i, a in enumerate(o.acts):
            cum += r.choice([0, 0, 0, 1, 1, 2])
            as_ = a.ps + td(cum)
            if prev is not None:
                kind, lag = o.chain[i][2]
                as_ = max(as_, prev.af + td(1 + lag)) if kind == "FS" else max(as_, prev.as_ + td(lag))
            if i in o.after:
                oa, gap = o.after[i]
                as_ = max(as_, oa.af + td(1 + gap))
            as_ = workday(as_)
            dur = max(1, round(((a.pf - a.ps).days + 1) * r.uniform(0.8, 1.5)))
            af = workday(as_ + td(dur - 1))
            if a.step not in {"tk_shell1", "tk_shell2", "cbl_term"} and (af - as_).days >= 3 and r.random() < 0.15:
                cands = [d for d in RDAYS if as_ < d <= af]
                if cands:
                    h = r.choice(cands)
                    k = r.randint(2, 3)
                    res = next_rday(h, k)
                    ext = ((res or workday(h + td(k + 1))) - h).days
                    af = workday(af + td(ext))
                    cat = r.choice(HOLD_CATS[o.disc])
                    a.hold = (h, res, cat, r.choice(MATERIAL_BY_DISC[o.disc] if cat == "material" else HOLD_REASONS[cat]))
            a.as_, a.af = as_, af
            sub_items(r, o, a, prev)
            prev = a


def sub_items(r: random.Random, o: Obj, a: Act, prev: Act | None) -> None:
    if a.step not in SUB_ITEM_STEPS:
        return
    days = [d for d in workdays(a.as_, a.af) if not (a.hold and a.hold[0] <= d < (a.hold[1] or date.max))]
    if a.step == "pip_erect":
        num = o.extra["num"]
        dates = spread(r, days, o.extra["spools"])
        a.sub = [(f"{num}-SP-{k + 1:02d}", d) for k, d in enumerate(dates)]
    elif a.step in ("tk_shell1", "tk_shell2"):
        base = 1 if a.step == "tk_shell1" else 4
        a.sub = [(f"ring {base + k}", d) for k, d in enumerate(spread(r, days, 3))]
    elif a.step == "cbl_pull":
        a.sub = [(c[0], d) for c, d in zip(o.extra["cables"], spread(r, days, len(o.extra["cables"])))]
    elif a.step == "cbl_term":
        pulled = dict(prev.sub)
        sub = []
        for (cid, _), d in zip(prev.sub, spread(r, days, len(prev.sub))):
            sub.append((cid, max(d, workday(pulled[cid] + ONE))))
        a.sub = sorted(sub, key=lambda x: (x[1], x[0]))
    a.as_, a.af = min(d for _, d in a.sub), max(d for _, d in a.sub)
    for _, d in a.sub:
        a.daily[d] = a.daily.get(d, 0) + 1
    if a.step == "cbl_pull":   # metres, not count
        length = {c[0]: c[4] for c in o.extra["cables"]}
        a.daily = {}
        for cid, d in a.sub:
            a.daily[d] = a.daily.get(d, 0) + length[cid]


# --------------------------------------------------------------------------- field-report text

VERBS = {
    "start": {"formal": ["started", "commenced"], "abbrev": ["strtd", "start"], "synonym": ["begun", "taken up"], "hinglish": ["shuru", "chalu kiya"]},
    "finish": {"formal": ["completed"], "abbrev": ["done", "compl."], "synonym": ["finished", "over"], "hinglish": ["ho gaya", "complete ho gaya"]},
    "progress": {"formal": ["in progress"], "abbrev": ["WIP", "in prog."], "synonym": ["ongoing", "going on"], "hinglish": ["chal raha hai", "jaari hai"]},
    "hold": {"formal": ["on hold"], "abbrev": ["held up", "hold"], "synonym": ["stopped", "stuck"], "hinglish": ["ruka hua hai", "band hai"]},
    "resume": {"formal": ["resumed"], "abbrev": ["restarted"], "synonym": ["back on track"], "hinglish": ["phir se shuru"]},
}
TIMES = [("at 09:30", "09:30"), ("from 10 am", "10:00"), ("@ 14:00", "14:00"), ("at 8.30 am", "08:30")]
STYLE_W = [("formal", 20), ("abbrev", 18), ("synonym", 15), ("hinglish", 8), ("typo", 8), ("partial", 11),
           ("tag_only", 60), ("type_ambiguous", 12), ("wrong_area", 9)]
# kind -> (match_label, difficulty, expected_band, expected_outcome)
LABELS = {
    "formal": ("matched", "easy", "high", "auto_apply"),
    "sheet_easy": ("matched", "easy", "high", "auto_apply"),
    "abbrev": ("matched", "medium", "high", "auto_apply"), "synonym": ("matched", "medium", "high", "auto_apply"),
    "hinglish": ("matched", "medium", "high", "auto_apply"), "typo": ("matched", "medium", "high", "auto_apply"),
    "sheet_medium": ("matched", "medium", "high", "auto_apply"),
    "partial_unique": ("matched", "hard", "medium", "review"), "tag_only": ("matched", "hard", "medium", "review"),
    "wrong_area": ("matched", "hard", "medium", "review"), "conflicting_date": ("matched", "hard", "medium", "review"),
    "ambiguous_partial": ("ambiguous", "hard", "medium", "review"), "type_ambiguous": ("ambiguous", "hard", "medium", "review"),
    "coarser": ("ambiguous", "hard", "medium", "review"),
    "new_activity": ("unmatched", "na", "low", "unmatched"), "unknown_reference": ("unmatched", "na", "low", "unmatched"),
}
STYLE_CASES = {"abbrev": "abbreviation", "synonym": "terminology_variant", "hinglish": "hinglish", "typo": "typo",
               "partial_unique": "partial_description", "ambiguous_partial": "partial_description", "tag_only": "tag_only",
               "type_ambiguous": "type_ambiguous", "wrong_area": "wrong_area", "coarser": "granularity_coarser",
               "new_activity": "new_activity", "unknown_reference": "unknown_reference", "conflicting_date": "conflicting_date"}


def typo(r: random.Random, tpl: str) -> str:
    """Corrupt one plain word of a template (never identifiers or placeholders)."""
    words = tpl.split(" ")
    idx = [i for i, w in enumerate(words) if w.isalpha() and len(w) >= 5]
    if not idx:
        return tpl
    i = r.choice(idx)
    w = words[i]
    op = r.choice(["swap", "drop", "double"])
    j = r.randint(1, len(w) - 2)
    if op == "swap":
        nw = w[:j] + w[j + 1] + w[j] + w[j + 2:]
    elif op == "drop":
        vow = [k for k in range(1, len(w)) if w[k] in "aeiou"] or [j]
        k = r.choice(vow)
        nw = w[:k] + w[k + 1:]
    else:
        nw = w[:j] + w[j] + w[j:]
    if nw == w:
        nw = w[:-1]
    words[i] = nw
    return " ".join(words)


class World:
    """Truth plus everything needed to write field sources and labels."""

    def __init__(self, objs: list[Obj]):
        self.objs = objs
        self.leaves = [a for o in objs for a in o.acts]
        self.by_id = {a.id: a for a in self.leaves}
        self.by_desc = defaultdict(list)
        for a in self.leaves:
            if a.obj.desc:
                self.by_desc[(a.step, a.obj.desc)].append(a.id)
        self.truth: dict[tuple, dict] = {}       # (act_id, type, date) -> truth event
        for a in self.leaves:
            for et, d in [("start", a.as_), ("finish", a.af)] + ([("hold", a.hold[0]), ("resume", a.hold[1])] if a.hold else []):
                if in_window(d):
                    self.reg(a, et, d, delay=a.hold[2] if et == "hold" else None)
            for d, q in sorted(a.daily.items()):
                if in_window(d):
                    self.reg(a, "progress", d, qty=q, unit=STEPS[a.step].unit)
        self.items: list[dict] = []
        self.docs: list[dict] = []
        self.canon_count = Counter(t for o in objs for t in o.canon)

    def tag_unique(self, a: Act) -> bool:
        """True when the object's tag alone identifies this one activity."""
        o = a.obj
        return len(o.acts) == 1 and bool(o.canon) and all(self.canon_count[t] == 1 for t in o.canon)

    def reg(self, a: Act, et: str, d: date, qty=None, unit=None, delay=None) -> tuple:
        k = (a.id, et, d)
        self.truth.setdefault(k, {"activity_id": a.id, "event_type": et, "event_date": d, "event_time": None,
                                  "quantity": qty, "unit": unit, "delay_category": delay})
        return k

    def active(self, a: Act, d: date, slack: int = 7) -> list[Act]:
        return [x for x in a.obj.acts if x.as_ - td(slack) <= d <= x.af + td(slack)]

    def new_item(self, **kw) -> dict:
        item = {"item_id": f"IT-{len(self.items) + 1:04d}", **kw}
        self.items.append(item)
        return item


def date_phrase(r: random.Random, edate: date, rday: date) -> tuple[str, str | None]:
    if edate == rday:
        return r.choice(["", "", "", " today"]), None
    if edate == rday - ONE and r.random() < 0.6:
        return r.choice([" yesterday", " yday"]), "relative_date"
    return f" on {fmt_date(edate, r.choice(INLINE_DATE_FMTS))}", "explicit_date"


def make_item(w: World, r: random.Random, a: Act, et: str, edate: date, rday: date, doc: dict, lower: bool) -> dict:
    o, st = a.obj, STEPS[a.step]
    ph = st.ph
    styles = [(s, wt) for s, wt in STYLE_W if
              (s != "tag_only" or ph["tag_only"] or w.tag_unique(a)) and (s != "partial" or (ph["partial"] and o.desc)) and
              (s != "type_ambiguous" or len(w.active(a, rday)) >= 2) and (s != "wrong_area" or (o.canon and not o.area_in_id))]
    style = r.choices([s for s, _ in styles], [wt for _, wt in styles])[0]
    base = style if style in ("formal", "abbrev", "synonym", "hinglish") else r.choice(["formal", "abbrev", "synonym"])
    ident = r.choice(o.ids[base])
    tags, area = list(o.canon), (o.area if o.area_in_id else None)
    cands = [a.id]
    kind = style
    if style == "tag_only":
        tpl = r.choice(ph["tag_only"] or ["{id}"])
        ident = r.choice(o.ids["formal"] + o.ids["abbrev"])
        tags = [o.extra["tp"]] if "{tp}" in tpl else list(o.canon)
        objp = tpl.format(id=ident, tp=o.extra.get("tp", ""))
    elif style == "partial":
        objp = r.choice(ph["partial"]).format(desc=o.desc)
        tags, area = [], None
        same = w.by_desc[(a.step, o.desc)]
        kind = "partial_unique" if len(same) == 1 else "ambiguous_partial"
        cands = list(same)
    elif style == "type_ambiguous":
        objp = r.choice(["{id} work", "work at {id}", "{id} job"]).format(id=ident)
        cands = [x.id for x in w.active(a, rday)]
    else:
        tpl = r.choice(ph[base])
        if style == "typo":
            tpl = typo(r, tpl)
        objp = tpl.format(id=ident, desc=o.desc)
        if style == "wrong_area":
            wrong = r.choice([x for x in AREAS if x != o.area])
            objp += r.choice([" in Area-{n}", " (A{n})", " at area {n}"]).format(n=wrong[1])
            area = wrong
    vstyle = "hinglish" if style == "hinglish" else ("abbrev" if style in ("abbrev", "typo") else r.choice(["formal", "synonym"]))
    verb = r.choice(VERBS[et][vstyle])
    dtxt, dcase = date_phrase(r, edate, rday)
    hard = [c for c in [STYLE_CASES.get(kind), dcase] if c]
    qty = unit = time = reason = cat = None
    gran = "same"
    if et == "progress" and a.step in SUB_ITEM_STEPS:
        qty, unit, gran = a.daily[edate], st.unit, "finer"
        if unit == "rings":
            rings = [s for s, d in a.sub if d == edate]
            qtxt = (" & ".join(rings) if len(rings) > 1 else rings[0]) + " erected"
        else:
            qtxt = {"spools": f"{qty} spool{'s' if qty > 1 else ''} erected", "m": f"{qty} m pulled",
                    "cables": f"{qty} cable{'s' if qty > 1 else ''} terminated"}[unit]
        phrase = f"{objp} – {qtxt}{dtxt}"
        hard.append("granularity_finer")
    else:
        ttxt = ""
        if et == "start" and r.random() < 0.3:
            ttxt, time = (lambda t: (" " + t[0], t[1]))(r.choice(TIMES))
        qtxt = ""
        if et == "finish" and st.unit == "cum" and r.random() < 0.6:
            qty, unit = a.qty, "cum"
            qtxt = f" ({qty:g} cum)"
        rtxt = ""
        if et == "hold":
            cat, reason = a.hold[2], a.hold[3]
            rtxt = r.choice([" – {x}", " due to {x}", ", {x}"]).format(x=reason)
        phrase = f"{objp} {verb}{qtxt}{ttxt}{dtxt}{rtxt}"
    if lower:
        phrase, objp = phrase.lower(), objp.lower()
    key = w.reg(a, et, edate)
    if time and not w.truth[key]["event_time"]:
        w.truth[key]["event_time"] = time
    ml = LABELS[kind]
    return w.new_item(
        doc_id=doc["doc_id"], source_type="dpr", source_path=doc["path"], report_date=rday, discipline=DISCIPLINES[o.disc],
        source_span=phrase, activity_text=objp, event_type=et, stated_date=edate, event_time=time, quantity=qty, unit=unit,
        area=area, tags=tags, delay_reason=reason, delay_category=cat, event_key=key, match_label=ml[0], difficulty=ml[1],
        true_activity_id=a.id, candidate_activity_ids=cands, unmatched_type=None, new_work_key=None, suggested_parent_wbs=None,
        granularity=gran, expected_band=ml[2], expected_outcome=ml[3], hard_cases=hard, style=kind,
        late_report=edate != rday)


NEW_WORK = [  # unplanned work that must reach the planner as a new activity
    ("NW-01", "CIV", "A3", "Temporary drainage trench near PR-3 due to waterlogging", "temp drain trench nr PR-3 (water logging)", ["PR-3"]),
    ("NW-02", "CIV", "A3", "Additional PCC below pipe sleeper at road crossing RC-2", "extra PCC @ RC-2 sleeper", ["RC-2"]),
    ("NW-03", "CIV", "A1", "Chipping & repair of honeycombed concrete at V-102 pedestal", "V-102 pedestal honeycomb repair", ["V-102"]),
    ("NW-04", "PIP", "A3", "Additional pipe support AS-17 at PR-2 (field clash)", "extra support AS-17 PR-2 clash", ["AS-17", "PR-2"]),
    ("NW-05", "PIP", "A3", "Cut & re-weld of joint 1205-W12 after RT repair", "1205-W12 cut & reweld (RT reject)", ["LINE-1205"]),
    ("NW-06", "PIP", "A3", "Temporary strainer at P-101A suction for flushing", "temp strainer P-101A suction", ["P-101A"]),
    ("NW-07", "ROT", "A1", "Additional shim plates for K-301 skid", "K-301 extra shims", ["K-301"]),
    ("NW-08", "ELE", "A3", "Temporary power DB for welding machines in Area-3", "temp DB for welding m/c A3", []),
    ("NW-09", "ELE", "A4", "Extra cable trench crossing near tank farm road", "addl cable crossing tank farm road", []),
    ("NW-10", "INS", "A3", "Relocation of PT-2042 stand due to access issue", "PT-2042 stand shifting", ["PT-2042"]),
    ("NW-11", "HSE", "A3", "Temporary barricading & signage at excavation near P-102B", "barricading near P-102B pit", ["P-102B"]),
    ("NW-12", "HSE", "A1", "Additional eyewash station near chemical dosing skid", "extra eyewash nr dosing skid", []),
    ("NW-13", "CIV", "A4", "Re-excavation of T-401 drain pit after collapse", "T-401 drain pit re-excavation", ["T-401"]),
    ("NW-14", "PIP", "A1", "Hot tap connection on existing 24\" header (unplanned tie-in)", "hot tap tie-in on old 24\" header", []),
]
UNKNOWN_REFS = [  # references to objects that do not exist in the plan (typos or stale drawings)
    ("PIP", "pip_erect", "A3", line_ids(24, "P", "1209", "A1A"), ["LINE-1209"]),
    ("PIP", "pip_ht", "A3", line_ids(10, "W", "1219", "A1A"), ["LINE-1219"]),
    ("PIP", "pip_weld", "A1", line_ids(8, "P", "1109", "A1A"), ["LINE-1109"]),
    ("ROT", "pmp_grout", "A3", tag_ids("P-104A"), ["P-104A"]),
    ("SEQ", "eq_erect", "A1", tag_ids("V-105"), ["V-105"]),
    ("CIV", "fdn_pcc", "A3", tag_ids("P-104B"), ["P-104B"]),
    ("CIV", "fdn_exc", "A1", tag_ids("V-105"), ["V-105"]),
    ("CIV", "fdn_rcc", "A4", tag_ids("T-403"), ["T-403"]),
    ("ELE", "pnl_inst", "A2", tag_ids("MCC-3"), ["MCC-3"]),
    ("ELE", "tr_place", "A2", tag_ids("TR-3"), ["TR-3"]),
    ("INS", "jb_inst", "A3", tag_ids("JB-309"), ["JB-309"]),
    ("INS", "ins_inst", "A3", tag_ids("FT-2035"), ["FT-2035"]),
    ("HSE", "gd_inst", "A3", tag_ids("GD-305"), ["GD-305"]),
    ("HSE", "ss_inst", "A3", tag_ids("SS-305"), ["SS-305"]),
]
COARSE = {  # area-level statements that cover several plan activities
    "piping": (["Piping erection in {a}", "Pipe rack piping work {a}"], {"pip_erect", "pip_weld"}),
    "civil": (["Foundation works in {a}", "Civil work {a}"], {"fdn_exc", "fdn_pcc", "fdn_reb", "fdn_rcc", "fdn_bf"}),
    "electrical": (["Cable laying in {a}", "Electrical works {a}"], {"cbl_pull", "cbl_term", "earth", "tray"}),
    "mechanical": (["Equipment erection work {a}"], {"eq_erect", "eq_grout", "eq_int", "pmp_set", "pmp_grout", "tk_shell1", "tk_shell2", "tk_roof"}),
    "instrumentation": (["Instrument installation {a}"], {"ins_inst", "ins_tube", "jb_inst"}),
}


def schedule_extras() -> dict[tuple, list]:
    """(group, report_day) -> injected new-work / unknown-reference mentions."""
    out: dict[tuple, list] = defaultdict(list)

    def place(group: str, d: date | None, entry):
        while d is not None and (group, d) in MISSING_DPRS:
            d = next_rday(d)
        if d is not None:
            out[(group, d)].append(entry)

    for nw in NEW_WORK:
        r = rng_for("nw", nw[0])
        d1 = r.choice(RDAYS[:-3])
        place(DISC_GROUP[nw[1]], d1, ("new", nw, "start", d1))
        if r.random() < 0.75:
            d2 = next_rday(d1, r.randint(1, 3))
            place(DISC_GROUP[nw[1]], d2, ("new", nw, "finish", d2))
    for i, u in enumerate(UNKNOWN_REFS):
        r = rng_for("unk", i)
        d = r.choice(RDAYS)
        place(DISC_GROUP[u[0]], d, ("unknown", u, r.choice(["start", "finish", "progress"]), d))
    return out


def report_day_for(a: Act, et: str, d: date) -> date | None:
    """Day the DPR mentions this event: same day (80%), next report day (15%), never (5%)."""
    x = rng_for("lag", a.id, et).random()
    if x < 0.05:
        return None
    rd = next_rday(d) if x < 0.20 else d
    group = DISC_GROUP[a.obj.disc]
    while rd is not None and (group, rd) in MISSING_DPRS:
        rd = next_rday(rd)
    return rd


def build_dprs(w: World, out: Path) -> None:
    extras = schedule_extras()
    by_rday: dict[tuple, list] = defaultdict(list)
    for (aid, et, d), _ in sorted(w.truth.items(), key=lambda kv: (kv[0][2], kv[0][0], kv[0][1])):
        if et == "progress":
            continue
        a = w.by_id[aid]
        if et == "start" and a.af == d:
            continue                       # same-day start+finish: the report says "done"
        rd = report_day_for(a, et, d)
        if rd:
            by_rday[(DISC_GROUP[a.obj.disc], rd)].append((a, et, d))
    seq = Counter()
    for rday in RDAYS:
        for group, g in GROUPS.items():
            if (group, rday) in MISSING_DPRS:
                continue
            seq[group] += 1
            r = rng_for("dpr", rday, group)
            informal = r.random() < g["informal"]
            lower = informal and r.random() < 0.4
            path = f"reports/dpr_{rday.isoformat()}_{group}.txt"
            doc = {"doc_id": f"DPR-{rday.isoformat()}-{group}", "source_type": "dpr", "path": path, "report_date": rday,
                   "discipline_group": group, "layout": "informal" if informal else "structured"}
            events = by_rday.get((group, rday), [])
            touched = {a.id for a, _, _ in events}
            prog = []
            for a in w.leaves:
                if a.obj.disc not in g["discs"] or a.id in touched or not (a.as_ <= rday <= a.af):
                    continue
                if a.hold and a.hold[0] <= rday < (a.hold[1] or date.max):
                    continue
                if a.step in SUB_ITEM_STEPS:
                    if rday in a.daily and r.random() < {"pip_erect": 0.6, "tk_shell1": 0.7, "tk_shell2": 0.7}.get(a.step, 0.45):
                        prog.append((a, "progress", rday))
                elif a.as_ < rday < a.af and r.random() < 0.18:
                    prog.append((a, "progress", rday))
            chosen = events[:10] + prog[: max(0, 10 - len(events))]
            work, holds = [], []
            for a, et, d in chosen:
                it = make_item(w, r, a, et, d, rday, doc, lower)
                (holds if et == "hold" else work).append(it)
            for kind, spec, et, d in extras.get((group, rday), []):
                work.append(extra_item(w, r, kind, spec, et, d, rday, doc, lower))
            if group in COARSE and r.random() < 0.6:
                it = coarse_item(w, r, group, rday, doc, lower)
                if it:
                    work.append(it)
            r.shuffle(work)
            lines, noise = layout(w, r, doc, g, rday, seq[group], informal, lower, work, holds)
            doc["non_event_lines"] = noise
            doc["header_date_text"] = lines[3 if not informal else 0]
            (out / path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
            w.docs.append(doc)


def extra_item(w: World, r: random.Random, kind: str, spec, et: str, d: date, rday: date, doc: dict, lower: bool) -> dict:
    style = r.choice(["formal", "abbrev"])
    dtxt, dcase = date_phrase(r, d, rday)
    if kind == "new":
        key, disc, area, formal, informal, tags = spec
        objp = formal if style == "formal" else informal
        verb = r.choice(VERBS[et][style])
        phrase = f"{objp} {verb}{dtxt}"
        lbl, extra = LABELS["new_activity"], dict(unmatched_type="new_activity", new_work_key=key,
                                                  suggested_parent_wbs=f"{PROJECT_CODE}.{area}.{disc}")
        hard = ["new_activity"]
    else:
        disc, step, area, ids, tags = spec
        ident = r.choice(ids[style])
        objp = r.choice(STEPS[step].ph[style]).format(id=ident, desc="")
        phrase = f"{objp} {r.choice(VERBS[et][style])}{dtxt}"
        lbl, extra = LABELS["unknown_reference"], dict(unmatched_type="unknown_reference", new_work_key=None,
                                                       suggested_parent_wbs=None)
        hard = ["unknown_reference"]
    if dcase:
        hard.append(dcase)
    if lower:
        phrase, objp = phrase.lower(), objp.lower()
    return w.new_item(
        doc_id=doc["doc_id"], source_type="dpr", source_path=doc["path"], report_date=rday, discipline=DISCIPLINES[disc],
        source_span=phrase, activity_text=objp, event_type=et, stated_date=d, event_time=None, quantity=None, unit=None,
        area=None, tags=list(tags), delay_reason=None, delay_category=None, event_key=None, match_label=lbl[0],
        difficulty=lbl[1], true_activity_id=None, candidate_activity_ids=[], granularity="same", expected_band=lbl[2],
        expected_outcome=lbl[3], hard_cases=hard, style=kind, late_report=False, **extra)


def coarse_item(w: World, r: random.Random, group: str, rday: date, doc: dict, lower: bool) -> dict | None:
    tpls, steps = COARSE[group]
    by_area = {ar: [a.id for a in w.leaves if a.step in steps and a.obj.area == ar and a.as_ <= rday <= a.af] for ar in sorted(AREAS)}
    ok = [ar for ar, c in by_area.items() if len(c) >= 2]
    if not ok:
        return None
    area = r.choice(ok)
    cands = by_area[area]
    objp = r.choice(tpls).format(a=r.choice([f"Area-{area[1]}", f"A{area[1]}", f"area {area[1]}"]))
    phrase = f"{objp} {r.choice(VERBS['progress'][r.choice(['formal', 'synonym'])])}"
    if lower:
        phrase, objp = phrase.lower(), objp.lower()
    lbl = LABELS["coarser"]
    disc = GROUPS[group]["discs"][0]
    return w.new_item(
        doc_id=doc["doc_id"], source_type="dpr", source_path=doc["path"], report_date=rday, discipline=DISCIPLINES[disc],
        source_span=phrase, activity_text=objp, event_type="progress", stated_date=rday, event_time=None, quantity=None,
        unit=None, area=area, tags=[], delay_reason=None, delay_category=None, event_key=None, match_label=lbl[0],
        difficulty=lbl[1], true_activity_id=None, candidate_activity_ids=cands, unmatched_type=None, new_work_key=None,
        suggested_parent_wbs=None, granularity="coarser", expected_band=lbl[2], expected_outcome=lbl[3],
        hard_cases=["granularity_coarser"], style="coarser", late_report=False)


WEATHER = ["Clear, 31°C", "Sunny, 33°C", "Cloudy, light drizzle in afternoon", "Humid, 30°C", "Heavy rain 14:00-16:00"]
SAFETY = ["Toolbox talk on working at height. No LTI.", "TBT: hot work precautions. Nil incident.",
          "Safety walk done with HSE. 1 near miss (dropped object) reported.", "PPE audit done. No incident."]


def layout(w, r, doc, g, rday, n, informal, lower, work, holds):
    """Write the report text; record each item's line/index and the lines that hold no events."""
    lines: list[str] = []
    noise: list[dict] = []

    def put(text: str, kind: str | None = None, its: list | None = None):
        lines.append(text)
        ln = len(lines)
        if its:
            for k, it in enumerate(its):
                it["locator"] = {"line": ln, "index": k}
                if len(its) > 1:
                    it["hard_cases"].append("multi_item_line")
        elif kind and text.strip():
            noise.append({"line": ln, "kind": kind})

    plan_ahead = [a for a in w.leaves if a.obj.disc in g["discs"] and rday < a.ps <= rday + td(4) and a.as_ > rday]
    plan_ahead = r.sample(plan_ahead, min(2, len(plan_ahead)))
    ahead_txt = [r.choice(STEPS[a.step].ph["formal"]).format(id=a.obj.ids["formal"][0], desc=a.obj.desc) for a in plan_ahead]
    manpower = f"{r.randint(18, 60)} nos" if informal else f"Supervisors {r.randint(1, 3)}, Skilled {r.randint(8, 30)}, Helpers {r.randint(10, 35)}"
    hdr_date = fmt_date(rday, r.choice(HEADER_DATE_FMTS))
    joiners = ["; ", ", ", " & "]
    if informal:
        put(f"CGS site update - {g['title'].lower()} - {hdr_date}", "header")
        rest = list(work)
        prefix = "Today: "
        if not rest:
            put("Today: no major activity, cleaning & housekeeping", "nil")
        while rest:
            k = min(len(rest), r.choice([1, 2, 3]))
            chunk, rest = rest[:k], rest[k:]
            put(prefix + "; ".join(i["source_span"] for i in chunk), its=chunk)
            prefix = "Also: "
        for it in holds:
            put("Hold: " + it["source_span"], its=[it])
        if ahead_txt:
            put("Tmrw: " + ", ".join(t.lower() if lower else t for t in ahead_txt), "plan_ahead")
        put(f"Manpower {manpower}. {r.choice(SAFETY)}", "manpower_safety")
        return lines, noise
    put("DAILY PROGRESS REPORT", "header")
    put(f"Project: {PROJECT_NAME}", "header")
    put(f"Discipline: {g['title']}    Contractor: {g['contractor']}", "header")
    put(f"Date: {hdr_date}    Report No: {g['code']}/DPR/{n:03d}", "header")
    put(f"Weather: {r.choice(WEATHER)}", "weather")
    put(f"Manpower: {manpower}", "manpower")
    put("")
    put("Work done today:", "section")
    i, num = 0, 1
    if not work:
        put("1. Nil (housekeeping only)", "nil")
    while i < len(work):
        k = 2 if i + 1 < len(work) and r.random() < 0.15 else 1
        chunk = work[i:i + k]
        put(f"{num}. " + r.choice(joiners).join(it["source_span"] for it in chunk), its=chunk)
        i, num = i + k, num + 1
    put("")
    put("Hold / constraints:", "section")
    for it in holds:
        put(f"- {it['source_span']}", its=[it])
    if not holds:
        put("- Nil", "nil")
    put("")
    put("Plan for tomorrow:", "section")
    for t in ahead_txt or ["Continue ongoing works"]:
        put(f"- {t}", "plan_ahead")
    put("")
    put(f"Safety: {r.choice(SAFETY)}", "safety")
    put(f"Prepared by: Site Engineer ({g['title']})", "signature")
    return lines, noise


# --------------------------------------------------------------------------- spreadsheets

def sheet_item(w: World, doc: dict, a: Act | None, et: str, d_truth: date | None, stated: date, locator: dict, cells: dict,
               kind: str, qty=None, unit=None, tags=None, area=None, hard=None, unknown_disc=None) -> dict:
    key = w.reg(a, et, d_truth, qty=qty if et == "progress" else None, unit=unit) if a else None
    lbl = LABELS[kind]
    span = " | ".join(str(v) for v in cells.values())
    return w.new_item(
        doc_id=doc["doc_id"], source_type="spreadsheet", source_path=doc["path"], report_date=stated,
        discipline=DISCIPLINES[a.obj.disc if a else unknown_disc], source_span=span, activity_text=str(next(iter(cells.values()))),
        event_type=et, stated_date=stated, event_time=None, quantity=qty, unit=unit, area=area, tags=tags or [],
        delay_reason=None, delay_category=None, event_key=key, match_label=lbl[0], difficulty=lbl[1],
        true_activity_id=a.id if a else None, candidate_activity_ids=[a.id] if a else [],
        unmatched_type="unknown_reference" if kind == "unknown_reference" else None, new_work_key=None,
        suggested_parent_wbs=None, granularity="finer" if et == "progress" else "same", expected_band=lbl[2],
        expected_outcome=lbl[3], hard_cases=list(hard or []) + [c for c in [STYLE_CASES.get(kind)] if c], style=kind,
        late_report=False, locator=locator, cells={k: (v.isoformat() if isinstance(v, date) else v) for k, v in cells.items()})


def sheet_date(r: random.Random, d: date):
    return d if r.random() < 0.75 else fmt_date(d, r.choice(SHEET_DATE_FMTS))


def build_spreadsheets(w: World, out: Path) -> None:
    # 1. Piping spool erection tracker: one row per spool; finer than the plan's "Erect line" activity.
    r = rng_for("sheet", "piping")
    doc = {"doc_id": "XLS-piping-spool-tracker", "source_type": "spreadsheet", "path": "spreadsheets/piping_spool_erection_tracker.xlsx",
           "discipline_group": "piping", "sheet": "Spool Tracker", "header_row": 4,
           "column_mapping": {"Sr": None, "Line No.": "line_tag", "Spool No": "sub_item_id", "Dia (in)": "size", "Area": "area",
                              "Erected Dt": "date", "Status": "status", "Remarks": "remarks"}}
    hdr = ["Sr", "Line No.", "Spool No", "Dia (in)", "Area", "Erected Dt", "Status", "Remarks"]
    rows = [[f"SPOOL ERECTION TRACKER – {PROJECT_CODE} – SEPTEMBER 2026"], [f"Updated upto: {fmt_date(WINDOW_END, 'dmy_dot')}"], [], hdr]
    spools = sorted(((d, a, sid) for a in w.leaves if a.step == "pip_erect" for sid, d in a.sub if in_window(d)),
                    key=lambda x: (x[0], x[1].id, x[2]))
    fake = [(RDAYS[r.randint(0, 13)], None, f"1209-SP-0{k}") for k in (1, 2)]
    allrows = sorted(spools + fake, key=lambda x: (x[0], x[2]))
    conflict = set(r.sample(range(len(allrows)), 12))
    for n, (d, a, sid) in enumerate(allrows, 1):
        rr = rng_for("sheet", "piping", sid)
        if a is None:
            line, size, area, kind, hard = rr.choice(['24"-P-1209-A1A', "1209"]), 24, "A3", "unknown_reference", []
        else:
            o = a.obj
            short = rr.random() < 0.5
            line = rr.choice(o.ids["abbrev"][2:] + [o.extra["num"], o.ids["abbrev"][1]]) if short else o.tag
            size, area = int(o.tag.split('"')[0]), o.area
            kind, hard = ("sheet_medium", ["abbreviation"]) if short else ("sheet_easy", [])
        stated = d
        if n - 1 in conflict and a is not None:
            stated = next_rday(d) or RDAYS[RDAY_IDX[d] - 1]
            kind, hard = "conflicting_date", hard
        dcell = sheet_date(rr, stated)
        status = rr.choice(["Erected", "Erected", "✓", "Done", "erected"])
        remark = rr.choice(["", "", "", "fit-up ok", "support pending", "bolt tightening balance"])
        row = [n, line, sid, size, f"Area-{area[1]}" if rr.random() < 0.5 else area, dcell, status, remark]
        rows.append(row)
        cells = {"Line No.": line, "Spool No": sid, "Erected Dt": dcell, "Status": status}
        sheet_item(w, doc, a, "progress", d, stated, {"sheet": "Spool Tracker", "row": len(rows)}, cells, kind, qty=1, unit="spools",
                   tags=[f"LINE-{sid.split('-')[0]}"], area=area, hard=hard + ["granularity_finer"], unknown_disc="PIP")
    xlsx_min.write(out / doc["path"], [("Spool Tracker", rows, ["A1:H1"])])
    w.docs.append(doc)

    # 2. Electrical cable log: one row per cable (pull + optional termination); two sheets.
    r = rng_for("sheet", "electrical")
    doc = {"doc_id": "XLS-electrical-cable-log", "source_type": "spreadsheet", "path": "spreadsheets/electrical_cable_log.xlsx",
           "discipline_group": "electrical", "sheet": "Cable Log", "header_row": 1,
           "column_mapping": {"Cable No": "sub_item_id", "Frm": "from_location", "To": "to_location", "Size": "cable_size",
                              "Len(m)": "quantity", "Pulled?": "status", "Dt": "date", "Termn": "termination_status",
                              "Termn Dt": "termination_date"}}
    hdr = ["Cable No", "Frm", "To", "Size", "Len(m)", "Pulled?", "Dt", "Termn", "Termn Dt"]
    rows = [hdr]
    pulls = {a.obj.key: a for a in w.leaves if a.step == "cbl_pull"}
    terms = {a.obj.key: a for a in w.leaves if a.step == "cbl_term"}
    entries = []
    for key, a in pulls.items():
        tdates = dict(terms[key].sub)
        for (cid, src, dst, size, ln), (_, d) in zip(a.obj.extra["cables"], a.sub):
            if in_window(d):
                entries.append((d, cid, a, src, dst, size, ln, tdates.get(cid)))
    for k in (1, 2):
        entries.append((RDAYS[r.randint(2, 12)], f"C-MCC3-00{k}", None, "MCC-3", "LDB-A3-04", "4Cx16 sqmm", 45 + 10 * k, None))
    for d, cid, a, src, dst, size, ln, tdate in sorted(entries, key=lambda x: (x[0], x[1])):
        rr = rng_for("sheet", "electrical", cid)
        pulled_mark = rr.choice(["Y", "Yes", "✓", "done"])
        dcell = sheet_date(rr, d)
        term_ok = tdate is not None and in_window(tdate)
        tmark, tcell = (rr.choice(["Y", "✓"]), sheet_date(rr, tdate)) if term_ok else ("", None)
        rows.append([cid, src, dst, size, ln, pulled_mark, dcell, tmark, tcell])
        loc = {"sheet": "Cable Log", "row": len(rows)}
        if a is None:
            sheet_item(w, doc, None, "progress", None, d, {**loc, "field": "pull"}, {"Cable No": cid, "Frm": src, "Len(m)": ln, "Dt": dcell},
                       "unknown_reference", qty=ln, unit="m", tags=["MCC-3"], hard=["granularity_finer"], unknown_disc="ELE")
            continue
        sheet_item(w, doc, a, "progress", d, d, {**loc, "field": "pull"},
                   {"Cable No": cid, "Frm": src, "Len(m)": ln, "Pulled?": pulled_mark, "Dt": dcell}, "sheet_medium",
                   qty=ln, unit="m", tags=list(a.obj.canon), area=a.obj.area if a.obj.area_in_id else None, hard=["granularity_finer"])
        if term_ok:
            ta = terms[a.obj.key]
            sheet_item(w, doc, ta, "progress", tdate, tdate, {**loc, "field": "termination"},
                       {"Cable No": cid, "Termn": tmark, "Termn Dt": tcell}, "sheet_medium", qty=1, unit="cables",
                       tags=list(a.obj.canon), area=a.obj.area if a.obj.area_in_id else None, hard=["granularity_finer"])
    summary = [["Group", "Planned (m)", "Pulled to date (m)"]]
    for key, a in pulls.items():
        summary.append([a.obj.name, a.qty, sum(c[4] for c, (_, d) in zip(a.obj.extra["cables"], a.sub) if d <= WINDOW_END)])
    xlsx_min.write(out / doc["path"], [("Cable Log", rows, []), ("Summary", summary, [])])
    w.docs.append(doc)

    # 3. Instrument installation register: one row per instrument; install + tubing completion dates.
    r = rng_for("sheet", "instrumentation")
    doc = {"doc_id": "XLS-instrument-register", "source_type": "spreadsheet", "path": "spreadsheets/instrument_installation_register.xlsx",
           "discipline_group": "instrumentation", "sheet": "Register", "header_row": 2,
           "column_mapping": {"S.No": None, "Tag No": "tag", "Instrument": "description", "Loc": "area", "Mounted on": "date",
                              "Tubing": "tubing_date", "Remarks": "remarks"}}
    hdr = ["S.No", "Tag No", "Instrument", "Loc", "Mounted on", "Tubing", "Remarks"]
    rows = [["INSTRUMENT INSTALLATION REGISTER"], hdr]
    inst = [a for a in w.leaves if a.step == "ins_inst" and in_window(a.af)]
    tube = {a.obj.key: a for a in w.leaves if a.step == "ins_tube"}
    entries = [(a.af, a) for a in inst] + [(RDAYS[r.randint(3, 12)], None)]
    for n, (d, a) in enumerate(sorted(entries, key=lambda x: (x[0], x[1].id if x[1] else "~")), 1):
        rr = rng_for("sheet", "instrumentation", n)
        if a is None:
            tagtxt, desc, area = "FT-2035", "Flow transmitter", "A3"
        else:
            o = a.obj
            tagtxt = rr.choice([o.tag, o.tag, o.tag.replace("-", " "), o.tag.replace("-", "")])
            desc, area = o.desc.capitalize(), o.area
        t = tube.get(a.obj.key) if a else None
        tdone = t is not None and in_window(t.af)
        tcell = sheet_date(rr, t.af) if tdone else ("N/A" if a and a.obj.tag.startswith("TT") else rr.choice(["pending", ""]))
        dcell = sheet_date(rr, d)
        rows.append([n, tagtxt, desc, rr.choice([f"Area-{area[1]}", area]), dcell, tcell, rr.choice(["", "", "stand ok", "cal cert recd"])])
        loc = {"sheet": "Register", "row": len(rows)}
        if a is None:
            sheet_item(w, doc, None, "finish", None, d, {**loc, "field": "install"}, {"Tag No": tagtxt, "Mounted on": dcell},
                       "unknown_reference", tags=["FT-2035"], unknown_disc="INS")
            continue
        kind = "sheet_easy" if tagtxt == a.obj.tag else "sheet_medium"
        sheet_item(w, doc, a, "finish", d, d, {**loc, "field": "install"}, {"Tag No": tagtxt, "Mounted on": dcell}, kind,
                   tags=[a.obj.tag], hard=[] if kind == "sheet_easy" else ["abbreviation"])
        if tdone:
            sheet_item(w, doc, t, "finish", t.af, t.af, {**loc, "field": "tubing"}, {"Tag No": tagtxt, "Tubing": tcell}, kind,
                       tags=[a.obj.tag], hard=[] if kind == "sheet_easy" else ["abbreviation"])
    xlsx_min.write(out / doc["path"], [("Register", rows, ["A1:G1"])])
    w.docs.append(doc)


# --------------------------------------------------------------------------- schedule export

def schedule_nodes(objs: list[Obj]) -> list[dict]:
    """DFS-ordered WBS tree: L1 project, L2 area, L3 discipline, L4 object, (L5 summary), L5/L6 activities."""
    nodes: list[dict] = []

    def node(nid, ntype, parent, level, name, wbs, **kw):
        n = {"node_id": nid, "node_type": ntype, "parent_id": parent, "level": level, "wbs_code": wbs, "name": name,
             "discipline": "", "area": "", "activity_type": "", "planned_start": None, "planned_finish": None,
             "planned_qty": "", "qty_unit": "", "predecessors": "", "actual_start": "", "actual_finish": "", **kw}
        nodes.append(n)
        return n

    def act_node(a: Act, parent: str, wbs: str):
        st = STEPS[a.step]
        node(a.id, "activity", parent, a.level, a.name, wbs, discipline=DISCIPLINES[a.obj.disc], area=a.obj.area,
             activity_type=st.atype, planned_start=a.ps, planned_finish=a.pf,
             planned_qty=("" if a.qty is None else a.qty), qty_unit=(st.unit or "") if a.qty is not None else "",
             predecessors=";".join(f"{p}:{k}{'+' if lag >= 0 else ''}{lag}" for p, k, lag in a.preds),
             actual_start=a.as_.isoformat() if a.as_ <= DATA_DATE else "",
             actual_finish=a.af.isoformat() if a.af <= DATA_DATE else "")

    node(PROJECT_CODE, "wbs", "", 1, PROJECT_NAME, PROJECT_CODE)
    for area, aname in AREAS.items():
        l2 = f"{PROJECT_CODE}.{area}"
        node(l2, "wbs", PROJECT_CODE, 2, f"{area} – {aname}", l2, area=area)
        for disc in DISCIPLINES:
            group = [o for o in objs if o.area == area and o.disc == disc]
            if not group:
                continue
            l3 = f"{l2}.{disc}"
            node(l3, "wbs", l2, 3, f"{DISC_TITLE[disc]} – {area}", l3, discipline=DISCIPLINES[disc], area=area)
            for o in group:
                l4 = f"{l3}.{o.key}"
                node(l4, "wbs", l3, 4, o.name, l4, discipline=DISCIPLINES[disc], area=area)
                parent = l4
                if o.summary:
                    sid = f"{o.disc}-{o.area}-{o.key}"
                    node(sid, "summary", l4, 5, o.summary, l4, discipline=DISCIPLINES[disc], area=area)
                    parent = sid
                for a in o.acts:
                    act_node(a, parent, l4)
    by_id = {n["node_id"]: n for n in nodes}
    for n in reversed(nodes):   # roll planned dates up the tree
        p = by_id.get(n["parent_id"])
        if p and n["planned_start"]:
            p["planned_start"] = min(filter(None, [p["planned_start"], n["planned_start"]]))
            p["planned_finish"] = max(filter(None, [p["planned_finish"], n["planned_finish"]]))
    for n in nodes:
        n["planned_duration_days"] = (n["planned_finish"] - n["planned_start"]).days + 1
        n["planned_start"], n["planned_finish"] = n["planned_start"].isoformat(), n["planned_finish"].isoformat()
    return nodes


SCHEDULE_COLS = ["node_id", "node_type", "parent_id", "level", "wbs_code", "name", "discipline", "area", "activity_type",
                 "planned_start", "planned_finish", "planned_duration_days", "planned_qty", "qty_unit", "predecessors",
                 "actual_start", "actual_finish"]
MSP_NS = "http://schemas.microsoft.com/project"
EXT_ATTRS = [("188743731", "Text1", "Activity ID"), ("188743734", "Text2", "Discipline"), ("188743737", "Text3", "Area")]


def write_mspdi(path: Path, nodes: list[dict]) -> None:
    ET.register_namespace("", MSP_NS)
    q = lambda t: f"{{{MSP_NS}}}{t}"

    def sub(parent, tag, text=None):
        e = ET.SubElement(parent, q(tag))
        if text is not None:
            e.text = str(text)
        return e

    uid = {n["node_id"]: i + 1 for i, n in enumerate(nodes)}
    children = defaultdict(list)
    for n in nodes:
        children[n["parent_id"]].append(n["node_id"])
    outline: dict[str, str] = {}

    def number(nid, prefix):
        outline[nid] = prefix
        for k, c in enumerate(children[nid], 1):
            number(c, f"{prefix}.{k}")

    number(PROJECT_CODE, "1")
    root = ET.Element(q("Project"))
    sub(root, "SaveVersion", 14)
    sub(root, "Name", f"{PROJECT_CODE}.xml")
    sub(root, "Title", PROJECT_NAME)
    sub(root, "ScheduleFromStart", 1)
    sub(root, "StartDate", f"{nodes[0]['planned_start']}T08:00:00")
    sub(root, "FinishDate", f"{nodes[0]['planned_finish']}T17:00:00")
    sub(root, "StatusDate", f"{DATA_DATE.isoformat()}T17:00:00")
    sub(root, "MinutesPerDay", 480)
    ea = sub(root, "ExtendedAttributes")
    for fid, fname, alias in EXT_ATTRS:
        x = sub(ea, "ExtendedAttribute")
        sub(x, "FieldID", fid)
        sub(x, "FieldName", fname)
        sub(x, "Alias", alias)
    tasks = sub(root, "Tasks")
    for n in nodes:
        t = sub(tasks, "Task")
        sub(t, "UID", uid[n["node_id"]])
        sub(t, "ID", uid[n["node_id"]])
        sub(t, "Name", n["name"])
        sub(t, "WBS", n["wbs_code"])
        sub(t, "OutlineNumber", outline[n["node_id"]])
        sub(t, "OutlineLevel", n["level"])
        sub(t, "Start", f"{n['planned_start']}T08:00:00")
        sub(t, "Finish", f"{n['planned_finish']}T17:00:00")
        sub(t, "Duration", f"PT{n['planned_duration_days'] * 8}H0M0S")
        sub(t, "Milestone", 0)
        sub(t, "Summary", 0 if n["node_type"] == "activity" else 1)
        if n["actual_start"]:
            sub(t, "ActualStart", f"{n['actual_start']}T08:00:00")
        if n["actual_finish"]:
            sub(t, "ActualFinish", f"{n['actual_finish']}T17:00:00")
        for p in filter(None, n["predecessors"].split(";")):
            pid, rest = p.split(":")
            link = sub(t, "PredecessorLink")
            sub(link, "PredecessorUID", uid[pid])
            sub(link, "Type", 1 if rest.startswith("FS") else 3)
            sub(link, "LinkLag", int(rest[2:]) * 4800)     # tenths of minutes, 8 h days
            sub(link, "LagFormat", 7)
        for (fid, _, _), val in zip(EXT_ATTRS, [n["node_id"] if n["node_type"] == "activity" else "", n["discipline"], n["area"]]):
            if val:
                x = sub(t, "ExtendedAttribute")
                sub(x, "FieldID", fid)
                sub(x, "Value", val)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


# --------------------------------------------------------------------------- ground truth & manifest

LABEL_COLS = ["item_id", "split", "source_type", "doc_id", "source_path", "locator", "report_date", "discipline", "source_span",
              "event_type", "stated_date", "event_key", "truth_date", "match_label", "difficulty", "true_activity_id",
              "candidate_activity_ids", "unmatched_type", "new_work_key", "suggested_parent_wbs", "granularity",
              "expected_band", "expected_outcome", "hard_cases"]
EXTRACT_FIELDS = ["item_id", "locator", "source_span", "activity_text", "event_type", "date", "time", "quantity", "unit",
                  "discipline", "area", "tags", "delay_reason", "delay_category"]


def iso(v):
    return v.isoformat() if isinstance(v, date) else v


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, lineterminator="\n")
        wr.writerow(cols)
        for row in rows:
            wr.writerow(["" if row.get(c) is None else iso(row.get(c)) for c in cols])


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=iso) + "\n", encoding="utf-8", newline="")


def locator_str(loc: dict) -> str:
    return ";".join(f"{k}={v}" for k, v in loc.items())


def finalize(w: World, out: Path, nodes: list[dict]) -> dict:
    # event keys: stable numbering by (date, activity, type)
    order = {"start": 0, "progress": 1, "hold": 2, "resume": 3, "finish": 4}
    keys = sorted(w.truth, key=lambda k: (k[2], k[0], order[k[1]]))
    ev_id = {k: f"EV-{i + 1:04d}" for i, k in enumerate(keys)}
    refs = Counter(it["event_key"] for it in w.items if it["event_key"])
    docs_per_key = defaultdict(set)
    for it in w.items:
        if it["event_key"]:
            docs_per_key[it["event_key"]].add(it["doc_id"])
    for it in w.items:
        k = it["event_key"]
        if k and len(docs_per_key[k]) > 1 and "duplicate_cross_source" not in it["hard_cases"]:
            it["hard_cases"].append("duplicate_cross_source")
        if it.get("late_report"):
            it["hard_cases"].append("late_report")
        it["truth_date"] = k[2] if k else None
        split_day = k[2] if k else it["stated_date"]
        it["split"] = "dev" if RDAY_IDX.get(split_day, RDAY_IDX.get(it["report_date"], 0)) % 2 == 0 else "test"
        it["event_key_id"] = ev_id[k] if k else None

    label_rows = []
    for it in w.items:
        row = {c: it.get(c) for c in LABEL_COLS}
        row.update(locator=locator_str(it["locator"]), event_key=it["event_key_id"],
                   candidate_activity_ids=";".join(it["candidate_activity_ids"]), hard_cases=";".join(sorted(set(it["hard_cases"]))))
        label_rows.append(row)
    gt = out / "ground_truth"
    write_csv(gt / "labels.csv", LABEL_COLS, label_rows)

    truth_rows = []
    for k in keys:
        t = w.truth[k]
        truth_rows.append({"event_key": ev_id[k], **t, "n_items": refs.get(k, 0)})
    write_csv(gt / "truth_events.csv", ["event_key", "activity_id", "event_type", "event_date", "event_time", "quantity", "unit",
                                        "delay_category", "n_items"], truth_rows)

    act_rows = []
    for a in w.leaves:
        o = a.obj
        status = ("completed" if a.af <= WINDOW_END else "on_hold" if a.hold and a.hold[0] <= WINDOW_END < (a.hold[1] or date.max)
                  else "in_progress" if a.as_ <= WINDOW_END else "not_started")
        tags = list(o.canon) + ([o.extra["tp"]] if a.step == "pip_ht" else [])
        act_rows.append({"activity_id": a.id, "object_key": o.key, "step_key": a.step, "description": o.desc,
                         "canonical_tags": ";".join(tags), "true_actual_start": a.as_ if a.as_ <= WINDOW_END else None,
                         "true_actual_finish": a.af if a.af <= WINDOW_END else None, "status_at_window_end": status})
    write_csv(gt / "activity_truth.csv", ["activity_id", "object_key", "step_key", "description", "canonical_tags",
                                          "true_actual_start", "true_actual_finish", "status_at_window_end"], act_rows)

    nw_items = Counter(it["new_work_key"] for it in w.items if it["new_work_key"])
    write_csv(gt / "new_work.csv", ["new_work_key", "discipline", "area", "description", "suggested_parent_wbs", "tags", "n_items"],
              [{"new_work_key": k, "discipline": DISCIPLINES[d], "area": a, "description": f, "suggested_parent_wbs": f"{PROJECT_CODE}.{a}.{d}",
                "tags": ";".join(t), "n_items": nw_items.get(k, 0)} for k, d, a, f, _, t in NEW_WORK])

    by_doc = defaultdict(list)
    for it in w.items:
        x = {f: it.get(f) for f in EXTRACT_FIELDS}
        x["date"] = it["stated_date"]
        if it["source_type"] == "spreadsheet":
            x["cells"] = it["cells"]
        by_doc[it["doc_id"]].append(x)
    write_json(gt / "expected_extraction.json", {"documents": [{**d, "items": by_doc.get(d["doc_id"], [])} for d in w.docs]})

    dev = [d.isoformat() for d in RDAYS if RDAY_IDX[d] % 2 == 0]
    write_json(gt / "splits.json", {"rule": "items split by the report-day index of their truth event date (else stated date): even=dev, odd=test",
                                    "dev_days": dev, "test_days": [d.isoformat() for d in RDAYS if d.isoformat() not in dev]})

    write_json(out / "glossary.json", GLOSSARY)

    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name not in ("manifest.json", "README.md"))
    stats = dataset_stats(w, nodes)
    manifest = {"seed": SEED, "generator_version": GENERATOR_VERSION, "project_code": PROJECT_CODE, "data_date": DATA_DATE,
                "report_window": [WINDOW_START, WINDOW_END], "report_days": RDAYS,
                "missing_reports": sorted(f"{g}@{d.isoformat()}" for g, d in MISSING_DPRS),
                "target_mix": TARGET_MIX, "stats": stats,
                "files": {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    write_json(out / "manifest.json", manifest)
    return manifest


def dataset_stats(w: World, nodes: list[dict]) -> dict:
    items = w.items
    hc = Counter(c for it in items for c in set(it["hard_cases"]))
    return {
        "schedule_nodes": len(nodes), "leaf_activities": len(w.leaves),
        "activities_by_discipline": dict(sorted(Counter(DISCIPLINES[a.obj.disc] for a in w.leaves).items())),
        "dpr_files": sum(1 for d in w.docs if d["source_type"] == "dpr"),
        "spreadsheet_files": sum(1 for d in w.docs if d["source_type"] == "spreadsheet"),
        "labelled_items": len(items),
        "items_by_source": dict(sorted(Counter(it["source_type"] for it in items).items())),
        "match_label": dict(sorted(Counter(it["match_label"] for it in items).items())),
        "difficulty": dict(sorted(Counter(it["difficulty"] for it in items).items())),
        "expected_outcome": dict(sorted(Counter(it["expected_outcome"] for it in items).items())),
        "split": dict(sorted(Counter(it["split"] for it in items).items())),
        "hard_cases": dict(sorted(hc.items())),
        "truth_events": len(w.truth),
        "truth_events_reported": sum(1 for k in w.truth if any(it["event_key"] == k for it in items)),
        "new_work_definitions": len(NEW_WORK),
    }


GLOSSARY = {
    "_note": "Field vocabulary used by site reports. Phase 2/3 normalization input; also a CAG prefix candidate.",
    "abbreviations": {
        "fdn": "foundation", "excvn": "excavation", "exc.": "excavation", "exc": "excavation", "pcc": "plain cement concrete (civil) | power control centre (electrical)",
        "rcc": "reinforced cement concrete", "b/f": "backfilling", "r/f": "reinforcement", "s/f": "shuttering (formwork)",
        "shutt.": "shuttering", "ftgs": "footings", "str.": "structural", "s/s": "substation", "bldg": "building", "brkwk": "brickwork",
        "col.": "column", "bm": "beam", "swd": "storm water drain", "ct-n/ct-s": "cable trench north/south",
        "erec": "erection", "erctn": "erection", "wldg": "welding", "ndt": "non-destructive testing", "rt": "radiography testing",
        "ht": "hydrotest", "hydro": "hydrotest", "reinst.": "reinstatement", "reinstmt": "reinstatement", "tp": "test pack",
        "ps": "pipe support", "supp.": "support", "l-": "line (piping)", "rcpt": "receipt", "insp": "inspection", "algn": "alignment",
        "grtg": "grouting", "crs": "courses", "btm": "bottom", "lo": "lube oil", "mrt": "mechanical run test", "trafo": "transformer",
        "instln": "installation", "cbl": "cable", "cbls": "cables", "fdrs": "feeders", "termn": "termination",
        "g&t": "glanding & termination", "ir": "insulation resistance", "ep": "earth pit", "c/t": "cable tray", "ltg": "lighting",
        "mcc": "motor control centre", "ht-swbd": "high-tension switchboard", "ldb": "lighting distribution board", "mtd": "mounted",
        "it": "impulse tubing", "jb": "junction box", "inst.": "instrument", "chk": "check", "lc": "loop check", "dcs": "distributed control system",
        "ccr": "central control room", "mc": "marshalling cabinet", "gd": "gas detector", "f&g": "fire & gas", "fap": "fire alarm panel",
        "ws": "windsock", "ss-": "safety shower", "wip": "work in progress", "in prog.": "in progress", "compl.": "completed",
        "strtd": "started", "yday": "yesterday", "tmrw": "tomorrow", "nr": "near", "addl": "additional", "temp": "temporary",
        "m/c": "machine", "tbt": "toolbox talk", "lti": "lost time injury", "nos": "numbers", "cum": "cubic metre",
    },
    "hinglish": {
        "khudai": "excavation", "dhalai": "concrete casting", "bharai": "backfilling", "sariya bandhai": "rebar tying",
        "chhat": "roof", "eent": "brick", "naali": "drain", "khinchai": "pulling", "bichhana": "laying", "lagana": "install",
        "rakhna": "place", "banana": "fabricate", "neeche": "lower", "upar": "upper", "kaam": "work",
        "shuru": "started", "chalu kiya": "started", "ho gaya": "completed", "complete ho gaya": "completed",
        "chal raha hai": "in progress", "jaari hai": "ongoing", "ruka hua hai": "on hold", "band hai": "stopped",
        "phir se shuru": "resumed", "ka/ki/ko/pe/ke": "grammatical particles (ignore)",
    },
    "event_verbs": {et: sorted({v for s in VERBS[et].values() for v in s}) for et in VERBS},
    "status_words_in_sheets": {"finish": ["Erected", "erected", "Done", "done", "✓", "Y", "Yes"], "pending": ["pending", ""],
                               "not_applicable": ["N/A"]},
    "tag_conventions": {
        "equipment": "letter code + number + optional train suffix, e.g. P-101A pump, V-101 vessel, E-101 exchanger, T-401 tank, K-301 compressor; written P101A, P-101 A",
        "piping_line": 'size"-service-number-spec, e.g. 24"-P-1203-A1A; field writes L-1203, L1203, P-1203, line 1203, 1203 line; canonical LINE-1203',
        "test_pack": "TP-0NN, one per hydrotest",
        "spool": "<line number>-SP-NN (finer than the plan)",
        "instrument": "FT/PT/LT/TT-NNNN; written FT2031, FT 2031",
        "electrical": "TR-n transformer, MCC-n, PCC-n, HT-SWBD-n panels; cable numbers C-<group>-NNN",
        "other": "JB-NNN junction box, GD-NNN gas detector, SS-NNN safety shower, PR-n pipe rack, CT-N/S cable trench, MC-n, FAP-n, WS-n",
    },
    "delay_categories": {c: r for c, r in HOLD_REASONS.items()},
    "date_formats_seen": ["dd/mm/yyyy", "dd/mm/yy", "dd.mm.yyyy", "dd.mm.yy", "dd-Mon-yy", "Mon d, yyyy", "yyyy-mm-dd",
                          "dth Sept yyyy", "d/m", "d-Mon", "Excel date serial", "yesterday / yday / today (relative to report date)"],
}


def generate(out: Path = DEFAULT_OUT) -> dict:
    out = Path(out)
    for sub in ("schedule", "reports", "spreadsheets", "ground_truth"):
        if (out / sub).exists():
            shutil.rmtree(out / sub)
        (out / sub).mkdir(parents=True)
    objs = build_catalog()
    build_truth(objs)
    w = World(objs)
    nodes = schedule_nodes(objs)
    write_csv(out / "schedule" / "schedule.csv", SCHEDULE_COLS, nodes)
    write_mspdi(out / "schedule" / "schedule.xml", nodes)
    build_dprs(w, out)
    build_spreadsheets(w, out)
    return finalize(w, out, nodes)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    m = generate(ap.parse_args().out)
    print(json.dumps(m["stats"], indent=2, default=iso))
