#!/usr/bin/env python3
"""
Process Diagram Editor
======================

A small desktop application (Python + PySide6) for drawing business process
diagrams from a deliberately limited set of primitives:

  * Process   - a resizable rectangle (a simple process)
  * Document  - a resizable rectangle whose upper-left corner is dog-eared
  * External  - a small gray square: a link to an external process. It has
                exactly one connection (an input OR an output), cannot be
                resized, and its name is written beside it, on the side
                opposite to the connection (right-aligned for an output,
                left-aligned for an input).
  * Comment   - a plain text block: no border, no fill, sized by its text.
                It cannot be connected to or from anything, and its text can
                never be empty (an empty text becomes "Undef").

Rules enforced by the editor
  * A process may have any number of inputs and outputs.
  * Processes are never connected to each other directly - only through a
    document:
        Process  --> Document   the document is an OUTPUT of the process
        Document --> Process    the document is an INPUT of the process
  * Document-to-document links are not allowed either.
  * An external process follows the same rules as a process (it can only be
    connected to a document), but it accepts a single connection.
  * Connections are drawn as polylines with only horizontal and vertical
    segments, re-routed automatically. They always LEAVE a primitive
    through its right border and ENTER the next one through its left border.
  * Every connection gets its own attachment point on a border and its own
    lane, so two connections never start/end in the same point or merge.
    Attachment points snap to half of the grid size, and so does the
    position of an external process (all other primitives snap to the grid).

Usage
  * Pick a tool in the toolbar (or press its key):
        V  Select / move / resize        P  Add process
        D  Add document                  E  Add external process
        T  Add text comment              C  Connect
  * Select tool: click to select, drag to move, drag the square handles to
    resize, double-click (or F2) to rename, Delete to remove.
    Rubber-band on empty canvas selects several items.
  * Select a connection to get handles: round ones slide its end points
    along the borders (also past neighbouring ones), square ones move its
    segments. Double-click a
    connection (or Edit > Reset connection routing, Ctrl+R) to make it
    automatic again.
  * Connect tool: drag from one item to another (or click source, then
    click target). Valid targets are outlined in green while connecting.
  * Select ONE process (not an external process) and a table opens under the
    diagram: Input document | Role | Term | Process | Output document.
    Input/Output cells open a drop-down with the documents linked to the
    process (arrows into it / out of it); Role, Term and Process are text.
    A "set" is one Role/Term/Process; "Add row" gives the set another row so
    several input/output documents can be linked to it - Role, Term and
    Process then span all of its rows.
  * Select ONE document and a list of its files opens under the diagram.
    "Add files..." attaches copies of files, "Remove" detaches them and
    "Save copy..." writes an attached file back to disk. A document that has
    attachments shows a paper clip in its lower right corner.
  * Edit > Roles dictionary... (or the "Roles..." button above the process
    table) opens a separate window with the table Role | Description |
    Actual set. The actual set of a role is what it currently consists of:
    user names and/or other roles of the same dictionary. Double-click the
    cell (or press Enter in it, or use "Edit actual set...") to tick the
    included roles and the users. Every user already entered for any role is
    offered as a tick box (one person can hold several roles); new names are
    typed below the list. A role can never include itself,
    directly or through other roles. Renaming a role renames it in the
    process tables too; deleting one clears it there.
    In the process table the Role cell of a set is a drop-down list of the
    roles of the dictionary (one list per set).
  * Ctrl + mouse wheel zooms, middle mouse button pans, Esc cancels.
  * File > Save / Open: a diagram is stored as a tar archive with the
    extension .bpmn. It contains diagram.json (the diagram and the roles
    dictionary) and, for every attachment,
    attachments/<document id>/<file name>. (Plain .json diagrams written by
    earlier versions can still be opened.) PNG and SVG export included.
  * Besides files, a document can carry web links (Add link... in the panel
    under the diagram: a Description and the URL). They are listed with the
    files, opened with a double-click, and stored in the .bpmn file too. A
    document with at least one file or link shows the paper clip.
  * File > Reports exports two reports, as an HTML page or a CSV table:
      Roles      every role with its description, assigned roles and users
      Documents  every document that connects processes: its author role (and
                 that role's users), the process it comes from, the term given
                 and the documents it is based on - all read from the process
                 tables - plus the processes it is passed to.

Requirements:  pip install PySide6
"""
from __future__ import annotations

import atexit
import csv
import html
import io
import itertools
import json
import math
import os
import posixpath
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFontMetricsF,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QPolygonF,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

try:  # QtSvg ships with the regular PySide6 wheels, but stay defensive
    from PySide6.QtSvg import QSvgGenerator
except ImportError:  # pragma: no cover
    QSvgGenerator = None

APP_NAME = "Process Diagram Editor"
FILE_EXT = ".bpmn"
REPORT_FILTER = "HTML page (*.html);;CSV table for Excel (*.csv)"
FILE_FILTER = "Business process diagram (*.bpmn)"
OPEN_FILTER = "Business process diagram (*.bpmn *.json)"   # .json: legacy files

# --------------------------------------------------------------------------- #
# Constants / look & feel
# --------------------------------------------------------------------------- #
GRID = 20
MIN_W, MIN_H = 60, 40
HANDLE = 9            # visual size of a resize handle (px)
HANDLE_HIT = 13       # clickable size of a resize handle (px)
EAR = 18              # size of the dog-ear on documents

PROCESS, DOCUMENT, EXTERNAL, COMMENT = "process", "document", "external", "comment"
MODE_SELECT, MODE_PROCESS, MODE_DOCUMENT, MODE_CONNECT = (
    "select", "process", "document", "connect")
MODE_EXTERNAL = "external"
MODE_COMMENT = "comment"
UNDEF_TEXT = "Undef"      # what a text comment shows when its text is empty


def comment_text(text) -> str:
    """The text of a comment: one line, and never empty (it would be invisible)."""
    return " ".join(str(text).split()) or UNDEF_TEXT

C_OUTLINE = QColor("#2f3b4c")
C_ACCENT = QColor("#1f78e0")
C_SOURCE = QColor("#e8890c")
C_TARGET = QColor("#2e9e4f")
C_TEXT = QColor("#1b1f27")
C_PROCESS_FILL = QColor("#dbe9fb")
C_EXTERNAL_FILL = QColor("#c3c8d0")
C_DOC_FILL = QColor("#fff4c9")
C_DOC_FOLD = QColor("#e4cf84")
C_ARROW = QColor("#3b4658")

HANDLE_CURSORS = {
    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
}


# routing-begin  (pure geometry, no widgets - see tests)
MIN_STRAIGHT = 12.0   # minimum overlap of facing borders for one straight segment
MIN_FWD_GAP = 20.0    # minimum horizontal gap for a direct left-to-right route
STUB = 20.0           # lead-in / lead-out length when routing "backwards"
PORT_SNAP = GRID / 2.0         # attachment points sit on multiples of this (half grid)
PORT_GAP = 2 * PORT_SNAP       # minimum distance between two attachment points
PORT_MARGIN = 2.0     # attachment points keep this distance from the corners
LANE_GAP = 10.0       # preferred distance between parallel, overlapping segments
ARROW_LEN = 11.0      # length of the arrow head
BIG = 1e9
END_KEYS = ("src", "dst")        # handles that slide along a border


class Route:
    """Result of routing one connection."""

    __slots__ = ("case", "pts", "segs", "handles", "bases", "used")

    def __init__(self, case, pts, segs, handles, bases, used):
        self.case = case          # direct | below | above | round
        self.pts = pts            # polyline vertices (QPointF)
        self.segs = segs          # (orient, coord, lo, hi, key) for every segment
        self.handles = handles    # [(key, QPointF)] draggable handles
        self.bases = bases        # automatic value of every adjustable lane
        self.used = used          # value actually used


def route_case(src, dst) -> str:
    a, b = src.scene_rect(), dst.scene_rect()
    if b.left() - a.right() >= MIN_FWD_GAP:
        return "direct"           # target is to the right: Z shape or straight
    if b.top() > a.bottom():
        return "below"            # go right, down, back left, into the target
    if a.top() > b.bottom():
        return "above"
    return "round"                # go round both items


def _border_range(node, border: str) -> tuple[float, float]:
    """Range (scene y) on the 'r'/'l' border where connections may attach."""
    lo, hi = node.usable_span(border)
    lo, hi = lo + PORT_MARGIN, hi - PORT_MARGIN
    if hi < lo:
        lo = hi = (lo + hi) / 2
    return lo, hi


def _port_levels(node, border: str) -> list[float]:
    """Heights (scene y) where a connection may attach to the 'r'/'l' border:
    the multiples of PORT_SNAP that lie on it."""
    lo, hi = _border_range(node, border)
    k0 = math.ceil(lo / PORT_SNAP - 1e-9)
    k1 = math.floor(hi / PORT_SNAP + 1e-9)
    return [k * PORT_SNAP for k in range(k0, k1 + 1)] or [(lo + hi) / 2]


def _clearance(orient, coord, lo, hi, placed) -> float:
    """Distance to the nearest placed parallel segment that overlaps [lo, hi]."""
    if lo > hi:
        lo, hi = hi, lo
    d = BIG
    for o, c, l, h, _key in placed:
        if o == orient and min(h, hi) - max(l, lo) >= -1.0:
            d = min(d, abs(c - coord))
    return d


def _seg_conflict(orient, coord, lo, hi, placed, gap=LANE_GAP) -> bool:
    return _clearance(orient, coord, lo, hi, placed) < gap


def _pick_lane(base, cand, placed, lower, upper, steps) -> float:
    """Coordinate closest to `base` (within [lower, upper]) for which none of
    the segments cand(coord) -> [(orient, coord, lo, hi), ...] comes closer than
    LANE_GAP to an overlapping parallel segment that is already placed."""
    base = min(max(base, lower), upper)

    def clearance(c):
        return min((_clearance(o, k, lo, hi, placed) for o, k, lo, hi in cand(c)),
                   default=BIG)

    def acceptable(c, relaxed):
        segs = cand(c)                   # the first one is the lane itself
        if _clearance(*segs[0], placed) < LANE_GAP:
            return False
        # 2nd round: feeders only have to stay off other lines, not LANE_GAP away
        need = 1.0 if relaxed else LANE_GAP
        return all(_clearance(o, k, lo, hi, placed) >= need
                   for o, k, lo, hi in segs[1:])

    for relaxed in (False, True):
        for k in range(80):
            for sgn in ((0,) if k == 0 else steps):
                c = base + sgn * k * LANE_GAP
                if lower <= c <= upper and acceptable(c, relaxed):
                    return c
    # No lane with the preferred spacing exists (narrow gap): take the lane
    # that is as far from the others as possible.
    best, best_d = base, -1.0
    for k in range(60):
        for sgn in ((0,) if k == 0 else steps):
            c = base + sgn * k * 2.0
            if lower <= c <= upper:
                d = clearance(c)
                if d > best_d + 1e-9:
                    best, best_d = c, d
    return best


def assign_ports(node) -> None:
    """Give every connection on the node's right (outgoing) and left (incoming)
    border its own attachment point (sets conn.y1 / conn.y2). Attachment points
    sit on multiples of PORT_SNAP and are at least PORT_GAP apart."""
    for border in ("r", "l"):
        out = border == "r"
        conns = [c for c in node.connections if (c.source is node) == out]
        n = len(conns)
        if not n:
            continue
        lo, hi = _border_range(node, border)
        levels = _port_levels(node, border)
        m = len(levels)

        def manual(c):
            return c.src_t if out else c.dst_t

        def other_pos(c):
            o = (c.target if out else c.source).scene_rect().center()
            return (o.y(), o.x(), c.seq)

        fixed = [c for c in conns if manual(c) is not None]
        autos = sorted((c for c in conns if manual(c) is None), key=other_pos)
        slots = [lo + (i + 1) * (hi - lo) / (n + 1) for i in range(n)]
        pos = {}
        for c in fixed:                       # user-placed: stays where it is
            pos[id(c)] = lo + min(max(manual(c), 0.0), 1.0) * (hi - lo)
            nearest = min(range(len(slots)), key=lambda i: abs(slots[i] - pos[id(c)]))
            del slots[nearest]
        for c, slot in zip(autos, slots):     # the rest: evenly spread
            pos[id(c)] = slot
        free = {id(c) for c in autos}
        order = sorted(conns, key=lambda c: (pos[id(c)], c.seq))

        full = max(1, math.ceil(PORT_GAP / PORT_SNAP - 1e-9))   # levels between ports
        step = full if (n - 1) * full <= m - 1 else (1 if n - 1 <= m - 1 else 0)
        ys = {}
        if step == 0:                         # border too short for snapping
            for i, c in enumerate(order):
                ys[id(c)] = lo + (i + 1) * (hi - lo) / (n + 1)
        else:
            idx = {id(c): min(range(m), key=lambda i: abs(levels[i] - pos[id(c)]))
                   for c in conns}
            def relax(movable):
                """Keep `step` levels between neighbours; only `movable` give way."""
                for _ in range(12):
                    moved = False
                    for i in range(1, n):
                        p, q = order[i - 1], order[i]
                        if idx[id(q)] - idx[id(p)] < step:
                            if id(q) in movable or id(p) not in movable:
                                idx[id(q)] = min(idx[id(p)] + step, m - 1)
                            else:
                                idx[id(p)] = max(idx[id(q)] - step, 0)
                            moved = True
                    for i in range(n - 1, 0, -1):
                        p, q = order[i - 1], order[i]
                        if idx[id(q)] - idx[id(p)] < step:
                            if id(p) in movable or id(q) not in movable:
                                idx[id(p)] = max(idx[id(q)] - step, 0)
                            else:
                                idx[id(q)] = min(idx[id(p)] + step, m - 1)
                            moved = True
                    if not moved:
                        return True
                return False

            if not relax(free):               # hand-placed ports leave no room:
                relax({id(c) for c in conns})  # let them give way as well
            for c in conns:
                ys[id(c)] = levels[idx[id(c)]]
        for c in conns:
            if out:
                c.y1 = ys[id(c)]
            else:
                c.y2 = ys[id(c)]


def _straighten(conns) -> None:
    """A lone output facing a lone input gets one straight line if possible."""
    for c in conns:
        if c.src_t is not None or c.dst_t is not None:
            continue
        s, d = c.source, c.target
        if sum(1 for o in s.connections if o.source is s) != 1:
            continue
        if sum(1 for o in d.connections if o.target is d) != 1:
            continue
        if route_case(s, d) != "direct":
            continue
        sl, dl = _border_range(s, "r"), _border_range(d, "l")
        lo, hi = max(sl[0], dl[0]), min(sl[1], dl[1])
        y = round(((lo + hi) / 2) / PORT_SNAP) * PORT_SNAP
        if hi - lo >= MIN_STRAIGHT and lo - 1e-9 <= y <= hi + 1e-9:
            c.y1 = c.y2 = y


def build_route(c, placed) -> Route:
    """Orthogonal route of connection `c` (ports c.y1 / c.y2 must be set).

    It ALWAYS leaves the source through its RIGHT border and enters the target
    through its LEFT border. Adjustable lanes (keys): "lane" (Z shape), or
    "out", "mid", "in" (routes that have to turn back). Automatic lanes avoid
    the segments in `placed`; lanes with a manual offset in c.offsets are kept.
    """
    a, b = c.source.scene_rect(), c.target.scene_rect()
    sx, ex = a.right(), b.left()
    y1, y2 = c.y1, c.y2
    case = route_case(c.source, c.target)
    off = c.offsets
    P = QPointF
    bases, used = {}, {}

    def lane(key, base, cand, lower, upper, steps):
        """Resolve one adjustable lane; cand(v) lists every segment that moves
        with it (the lane itself and the feeders attached to it)."""
        bases[key] = base
        if key in off:
            v = min(max(base + off[key], lower), upper)
        else:
            v = _pick_lane(base, cand, placed, lower, upper, steps)
        used[key] = v
        return v

    ends = [("src", P(sx, y1)), ("dst", P(ex, y2))]
    if case == "direct":
        if abs(y1 - y2) < 0.5:
            pts = [P(sx, y1), P(ex, y1)]
            segs = [("h", y1, sx, ex, None)]
            return Route(case, pts, segs, ends, bases, used)
        x = lane("lane", (sx + ex) / 2,
                 lambda v: [("v", v, y1, y2), ("h", y1, sx, v), ("h", y2, v, ex)],
                 sx + 6, ex - ARROW_LEN - 1, (1, -1))
        pts = [P(sx, y1), P(x, y1), P(x, y2), P(ex, y2)]
        segs = [("h", y1, sx, x, None),
                ("v", x, min(y1, y2), max(y1, y2), "lane"),
                ("h", y2, x, ex, None)]
        return Route(case, pts, segs, ends + [("lane", P(x, (y1 + y2) / 2))],
                     bases, used)

    # --- the target is not to the right: leave right, turn back, enter left ---
    xo_lo = sx + 6
    xi_hi = ex - ARROW_LEN - 1
    if case in ("below", "above"):
        if case == "below":
            ylo, yhi = a.bottom() + 4, b.top() - 4
            ym0 = (a.bottom() + b.top()) / 2
        else:
            ylo, yhi = b.bottom() + 4, a.top() - 4
            ym0 = (b.bottom() + a.top()) / 2
        if ylo > yhi:
            ylo = yhi = ym0
        ym_steps = (1, -1)
        xo0, xi0 = sx + STUB, ex - STUB
    else:                                                    # round
        top = min(a.top(), b.top()) - STUB
        bottom = max(a.bottom(), b.bottom()) + STUB
        use_top = (abs(y1 - top) + abs(y2 - top)
                   <= abs(y1 - bottom) + abs(y2 - bottom))
        if use_top:
            ym0, ylo, yhi, ym_steps = top, -BIG, min(a.top(), b.top()) - 6, (-1,)
        else:
            ym0, ylo, yhi, ym_steps = bottom, max(a.bottom(), b.bottom()) + 6, BIG, (1,)
        xo0 = max(a.right(), b.right()) + STUB
        xi0 = min(a.left(), b.left()) - STUB
        xo_lo = max(a.right(), b.right()) + 6
        xi_hi = min(a.left(), b.left()) - ARROW_LEN - 1
    xo = lane("out", xo0, lambda v: [("v", v, y1, ym0), ("h", y1, sx, v)],
              xo_lo, BIG, (1, -1))
    xi = lane("in", xi0, lambda v: [("v", v, ym0, y2), ("h", y2, v, ex)],
              -BIG, xi_hi, (-1, 1))
    if case == "round" and "mid" in off:      # may be dragged to the other side
        bases["mid"] = ym0
        ym = ym0 + off["mid"]
        topb = min(a.top(), b.top()) - 6
        botb = max(a.bottom(), b.bottom()) + 6
        if topb < ym < botb:                  # not through the items: nearest side
            ym = topb if ym - topb <= botb - ym else botb
        used["mid"] = ym
    else:
        ym = lane("mid", ym0, lambda v: [("h", v, xo, xi)], ylo, yhi, ym_steps)
    pts = [P(sx, y1), P(xo, y1), P(xo, ym), P(xi, ym), P(xi, y2), P(ex, y2)]
    segs = [("h", y1, min(sx, xo), max(sx, xo), None),
            ("v", xo, min(y1, ym), max(y1, ym), "out"),
            ("h", ym, min(xo, xi), max(xo, xi), "mid"),
            ("v", xi, min(ym, y2), max(ym, y2), "in"),
            ("h", y2, min(xi, ex), max(xi, ex), None)]
    handles = ends + [("out", P(xo, (y1 + ym) / 2)),
                      ("mid", P((xo + xi) / 2, ym)),
                      ("in", P(xi, (ym + y2) / 2))]
    return Route(case, pts, segs, handles, bases, used)


def layout_connections(conns) -> None:
    """(Re)compute ports and routes of all connections so that no two of them
    share an attachment point or run on top of each other."""
    nodes = {}
    for c in conns:
        nodes[id(c.source)] = c.source
        nodes[id(c.target)] = c.target
    for n in nodes.values():
        assign_ports(n)
    _straighten(conns)
    for c in conns:
        case = route_case(c.source, c.target)
        if c.case is not None and c.case != case:
            c.offsets.clear()                 # old manual lanes no longer fit
        c.case = case
    # hand-made routes first, so the automatic ones make room for them
    order = sorted(conns, key=lambda c: (0 if c.offsets else 1, c.seq))
    placed = []
    for c in order:
        c.route = build_route(c, placed)
        placed.extend(c.route.segs)
    # refinement: re-place every route against ALL the others, because a
    # route placed early cannot see the lines of the ones placed after it
    for _ in range(3):
        before = [[(p.x(), p.y()) for p in c.route.pts] for c in order]
        for c in order:
            others = [s for o in order if o is not c for s in o.route.segs]
            c.route = build_route(c, others)
        if before == [[(p.x(), p.y()) for p in c.route.pts] for c in order]:
            break


def move_handle(conn, key, x, y, others, snap=True) -> bool:
    """Apply a handle drag (scene coords x, y). Returns False if the requested
    position would put the connection on top of another one (nothing changes).

    An end handle may be dragged past the neighbouring attachment points: the
    others give way and re-arrange themselves around the dragged one."""
    route = conn.route
    if route is None:
        return False

    def clashes(r, placed):  # segments of route r that sit on top of another line
        return sum(1 for s in r.segs if _seg_conflict(s[0], s[1], s[2], s[3], placed))

    if key in END_KEYS:                       # slide the end point along the border
        out = key == "src"
        node = conn.source if out else conn.target
        lo, hi = _border_range(node, "r" if out else "l")
        y = min(_port_levels(node, "r" if out else "l"), key=lambda v: abs(v - y))
        # lines of the neighbours on the same border will move out of the way
        skip = {id(o) for o in node.connections if (o.source is node) == out}
        placed = [s for o in others if id(o) not in skip and o.route is not None
                  for s in o.route.segs]
        old_t, old_y = (conn.src_t, conn.y1) if out else (conn.dst_t, conn.y2)
        t = 0.5 if hi <= lo else (y - lo) / (hi - lo)
        if out:
            conn.src_t, conn.y1 = t, y
        else:
            conn.dst_t, conn.y2 = t, y
        if clashes(build_route(conn, placed), placed) > clashes(route, placed):
            if out:                           # would run on top of another line
                conn.src_t, conn.y1 = old_t, old_y
            else:
                conn.dst_t, conn.y2 = old_t, old_y
            return False
        return True
    if key not in route.bases:                # move a segment
        return False
    placed = [s for o in others if o.route is not None for s in o.route.segs]
    coord = y if key == "mid" else x
    if snap:
        coord = round(coord / (GRID / 2)) * (GRID / 2)
    had, old = key in conn.offsets, conn.offsets.get(key)
    conn.offsets[key] = coord - route.bases[key]
    new = build_route(conn, placed)
    if clashes(new, placed) > clashes(route, placed):   # would make things worse
        if had:
            conn.offsets[key] = old
        else:
            del conn.offsets[key]
        return False
    conn.offsets[key] = new.used[key] - new.bases[key]
    return True
# routing-end


# table-model-begin  (pure data, no widgets - see tests)
class TableRow:
    """One row of a process table: an input and an output document (both optional)."""

    __slots__ = ("inp", "out")

    def __init__(self, inp=None, out=None):
        self.inp = inp
        self.out = out


class TableSet:
    """Role / Term / Process plus the rows of documents sharing them."""

    __slots__ = ("role", "term", "process", "rows")

    def __init__(self, role="", term="", process="", rows=None):
        self.role = role
        self.term = term
        self.process = process
        self.rows = rows if rows else [TableRow()]


def plain_name(node) -> str:
    return " ".join(node.text.split()) or f"(unnamed {node.NAME})"


def unique_labels(nodes) -> list[str]:
    """Display names for `nodes`; equal names get " (1)", " (2)" ... appended."""
    base = [plain_name(n) for n in nodes]
    total: dict[str, int] = {}
    for b in base:
        total[b] = total.get(b, 0) + 1
    seen: dict[str, int] = {}
    labels = []
    for b in base:
        if total[b] > 1:
            seen[b] = seen.get(b, 0) + 1
            labels.append(f"{b} ({seen[b]})")
        else:
            labels.append(b)
    return labels


def linked_docs(process, incoming: bool) -> list:
    """Documents linked to `process`: those with an arrow INTO it (incoming)
    or an arrow OUT of it, in the order the connections were made."""
    conns = sorted(process.connections, key=lambda c: c.seq)
    if incoming:
        return [c.source for c in conns if c.target is process]
    return [c.target for c in conns if c.source is process]


def sanitize_sets(sets, ins, outs) -> bool:
    """Forget documents that are no longer linked. True if anything changed."""
    ok_in, ok_out = {id(d) for d in ins}, {id(d) for d in outs}
    changed = False
    for st in sets:
        for r in st.rows:
            if r.inp is not None and id(r.inp) not in ok_in:
                r.inp, changed = None, True
            if r.out is not None and id(r.out) not in ok_out:
                r.out, changed = None, True
    return changed


def sets_to_list(sets, ids) -> list[dict]:
    """JSON form of a process table; `ids` maps id(node) -> file id."""
    def ref(node):
        return None if node is None else ids.get(id(node))

    return [{"role": st.role, "term": st.term, "process": st.process,
             "rows": [{"in": ref(r.inp), "out": ref(r.out)} for r in st.rows]}
            for st in sets]


def sets_from_list(data, by_id, ins, outs) -> list:
    """Inverse of sets_to_list. Unknown or no longer linked documents become
    empty cells instead of making the whole file unreadable."""
    ok_in, ok_out = {id(d) for d in ins}, {id(d) for d in outs}

    def ref(key, allowed):
        try:
            node = by_id.get(key)
        except TypeError:            # unhashable value in a hand-edited file
            return None
        return node if node is not None and id(node) in allowed else None

    result = []
    if not isinstance(data, list):
        return result
    for d in data:
        if not isinstance(d, dict):
            continue
        rows = [TableRow(ref(rd.get("in"), ok_in), ref(rd.get("out"), ok_out))
                for rd in (d.get("rows") or []) if isinstance(rd, dict)]
        result.append(TableSet(str(d.get("role", "")), str(d.get("term", "")),
                               str(d.get("process", "")), rows))
    return result
# table-model-end

# roles-begin  (pure data, no widgets - see tests)
def normalize_name(text) -> str:
    """Names of roles and users: surrounding and repeated blanks are dropped."""
    return " ".join(str(text).split())


def parse_usernames(text) -> list[str]:
    """User names typed or pasted by the user: separated by commas,
    semicolons or line breaks; duplicates are dropped."""
    text = str(text)
    for sep in (";", "\n", "\r", "\t"):
        text = text.replace(sep, ",")
    found: list[str] = []
    for part in text.split(","):
        name = normalize_name(part)
        if name and name not in found:
            found.append(name)
    return found


class Role:
    """One entry of the dictionary. Its actual set (what it currently consists
    of) is `users` (user names) plus `roles` (names of other dictionary roles)."""

    __slots__ = ("name", "description", "users", "roles")

    def __init__(self, name, description="", users=None, roles=None):
        self.name = name
        self.description = description
        self.users: list[str] = list(users or [])
        self.roles: list[str] = list(roles or [])


class RoleDictionary:
    """The roles of a diagram. Names are unique (ignoring case) and roles can
    never include each other in a loop."""

    def __init__(self):
        self.items: list[Role] = []

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def names(self) -> list[str]:
        return [r.name for r in self.items]

    def find(self, name) -> "Role | None":
        for r in self.items:
            if r.name == name:
                return r
        return None

    def has(self, name) -> bool:
        return self.find(name) is not None

    def _clash(self, name, ignore=None) -> "Role | None":
        key = normalize_name(name).casefold()
        for r in self.items:
            if r is not ignore and r.name.casefold() == key:
                return r
        return None

    def unique_name(self, base: str = "New role") -> str:
        name, n = base, 1
        while self._clash(name) is not None:
            n += 1
            name = f"{base} {n}"
        return name

    def add(self, name: str = "", description: str = "") -> Role:
        name = normalize_name(name)
        if name and self._clash(name) is not None:
            raise ValueError(f"A role named “{name}” already exists.")
        role = Role(name or self.unique_name(), description)
        self.items.append(role)
        return role

    def rename(self, old: str, new: str) -> str:
        """Rename a role (also where other roles include it). Returns the name
        actually used; raises ValueError if the new name is not acceptable."""
        role = self.find(old)
        if role is None:
            raise ValueError(f"There is no role “{old}”.")
        new = normalize_name(new)
        if not new:
            raise ValueError("A role needs a name.")
        if self._clash(new, ignore=role) is not None:
            raise ValueError(f"A role named “{new}” already exists.")
        for r in self.items:
            r.roles = [new if n == old else n for n in r.roles]
        role.name = new
        return new

    def remove(self, name: str) -> None:
        role = self.find(name)
        if role is None:
            return
        self.items.remove(role)
        for r in self.items:
            r.roles = [n for n in r.roles if n != name]

    def descendants(self, name: str) -> set:
        """Names of all roles that `name` includes, directly or indirectly."""
        seen: set = set()
        todo = [name]
        while todo:
            r = self.find(todo.pop())
            for child in (r.roles if r else []):
                if child not in seen:
                    seen.add(child)
                    todo.append(child)
        return seen

    def can_include(self, parent: str, child: str) -> bool:
        """May role `parent` include role `child` without creating a loop?"""
        if parent == child or not self.has(parent) or not self.has(child):
            return False
        return parent not in self.descendants(child)

    def set_members(self, name: str, users, roles) -> None:
        """Replace the actual set of a role. All-or-nothing."""
        role = self.find(name)
        if role is None:
            raise ValueError(f"There is no role “{name}”.")
        new_users: list[str] = []
        for u in users:
            u = normalize_name(u)
            if u and u not in new_users:
                new_users.append(u)
        new_roles: list[str] = []
        for n in roles:
            if n in new_roles:
                continue
            if not self.has(n):
                raise ValueError(f"There is no role “{n}”.")
            if not self.can_include(name, n):
                raise ValueError(f"“{name}” cannot include “{n}”: "
                                 "that would make a loop.")
            new_roles.append(n)
        role.users, role.roles = new_users, new_roles

    def all_users(self) -> list[str]:
        """Every user name used anywhere in the dictionary, one each, sorted."""
        found: dict[str, str] = {}
        for r in self.items:
            for u in r.users:
                found.setdefault(u.casefold(), u)
        return sorted(found.values(), key=lambda u: (u.casefold(), u))

    def roles_of_user(self, user: str) -> list[str]:
        """Names of the roles that list `user` directly."""
        return [r.name for r in self.items if user in r.users]

    def effective_users(self, name: str) -> list[str]:
        """Every user of the role, including those of the roles it includes."""
        order: list[str] = []
        seen: set = set()

        def walk(n: str) -> None:             # own users first, then each included role in turn
            if n in seen:
                return
            seen.add(n)
            r = self.find(n)
            if r is None:
                return
            for u in r.users:
                if u not in order:
                    order.append(u)
            for child in r.roles:
                walk(child)

        walk(name)
        return order

    def members_text(self, name: str) -> str:
        """One-line form of the actual set: [Included role], user, user ..."""
        r = self.find(name)
        if r is None:
            return ""
        return ", ".join([f"[{n}]" for n in r.roles] + list(r.users))

    def to_list(self) -> list[dict]:
        return [{"name": r.name, "description": r.description,
                 "users": list(r.users), "roles": list(r.roles)} for r in self.items]

    @classmethod
    def from_list(cls, data) -> "RoleDictionary":
        """Inverse of to_list. Never raises: whatever is unusable in a
        hand-edited file (bad types, duplicates, loops) is left out."""
        result = cls()
        if not isinstance(data, list):
            return result
        pending = []
        for d in data:
            if not isinstance(d, dict) or not isinstance(d.get("name"), str):
                continue
            name = normalize_name(d["name"])
            if not name or result._clash(name) is not None:
                continue
            users: list[str] = []
            for u in d.get("users") if isinstance(d.get("users"), list) else []:
                u = normalize_name(u) if isinstance(u, str) else ""
                if u and u not in users:
                    users.append(u)
            desc = d.get("description")
            role = Role(name, desc if isinstance(desc, str) else "", users)
            result.items.append(role)
            pending.append((role, d.get("roles")))
        for role, kids in pending:
            for k in kids if isinstance(kids, list) else []:
                k = normalize_name(k) if isinstance(k, str) else ""
                if k and k not in role.roles and result.can_include(role.name, k):
                    role.roles.append(k)
        return result
# roles-end

# reports-begin  (pure data, no widgets - see tests)
class Report:
    """A table ready to be written out: a title, column headers, rows of text
    and an optional explanatory note."""

    def __init__(self, title: str, headers, rows, note: str = ""):
        self.title = title
        self.headers = tuple(headers)
        self.rows = [tuple(r) for r in rows]
        self.note = note


def _one_line(text) -> str:
    return " ".join(str(text).split())


def roles_report(roles: RoleDictionary) -> Report:
    """Every role: description, the roles and users assigned to it directly,
    and everybody who ends up in it (users of the assigned roles included)."""
    rows = []
    for r in roles:
        rows.append((r.name, _one_line(r.description), ", ".join(r.roles),
                     ", ".join(r.users), ", ".join(roles.effective_users(r.name))))
    return Report(
        "Roles",
        ("Role", "Description", "Assigned roles", "Assigned users",
         "All users (including the users of assigned roles)"),
        rows)


def documents_report(nodes, roles: RoleDictionary) -> Report:
    """The documents that circulate between processes.

    One row per (document, process it comes from, set of the process table that
    lists it as an output). A set gives the author role, the term and the
    documents the work is based on (the inputs of the same set). A document the
    table does not describe yet still gets a row, with those cells empty."""
    docs = [n for n in nodes if n.KIND == DOCUMENT]
    procs = [n for n in nodes if n.KIND == PROCESS]
    exts = [n for n in nodes if n.KIND == EXTERNAL]
    label: dict[int, str] = {}
    for group, suffix in ((docs, ""), (procs, ""), (exts, " (external process)")):
        for n, text in zip(group, unique_labels(group)):
            label[id(n)] = text + suffix

    rows = []
    for doc in sorted((d for d in docs if d.connections),
                      key=lambda d: (label[id(d)].casefold(), label[id(d)])):
        conns = sorted(doc.connections, key=lambda c: c.seq)
        makers = [c.source for c in conns if c.target is doc]
        users_of = [c.target for c in conns if c.source is doc]
        passed_to = ", ".join(label[id(p)] for p in users_of)
        if not makers:
            rows.append((label[id(doc)], "", "", "(no source process)", "", "", "", passed_to))
        for maker in sorted(makers, key=lambda p: (label[id(p)].casefold(), label[id(p)])):
            sets = ([st for st in maker.table if any(r.out is doc for r in st.rows)]
                    if maker.KIND == PROCESS else [])
            if not sets:
                rows.append((label[id(doc)], "", "", label[id(maker)], "", "", "", passed_to))
            for st in sets:
                inputs: list = []
                for r in st.rows:
                    if r.inp is not None and r.inp not in inputs:
                        inputs.append(r.inp)
                role = _one_line(st.role)
                rows.append((
                    label[id(doc)], role,
                    ", ".join(roles.effective_users(role)) if roles.has(role) else "",
                    label[id(maker)], _one_line(st.process), _one_line(st.term),
                    ", ".join(label[id(d)] for d in inputs), passed_to))
    return Report(
        "Documents",
        ("Document", "Author (role)", "Users of the role", "From process", "Activity",
         "Term", "Based on documents", "Passed to"),
        rows,
        "Author, activity, term and source documents come from the process tables. "
        "A row with those cells empty means the table of that process does not "
        "describe the document yet.")


def csv_safe(value: str) -> str:
    """Keep spreadsheet programs from running a cell that starts like a formula."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def report_csv(report: Report) -> str:
    """The report as CSV text: ';' separated (what Excel expects in most of
    Europe), CRLF line ends. Write it as UTF-8 with a BOM."""
    buf = io.StringIO(newline="")
    out = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    out.writerow([csv_safe(h) for h in report.headers])
    for row in report.rows:
        out.writerow([csv_safe(c) for c in row])
    return buf.getvalue()


REPORT_CSS = """
body { font: 14px/1.45 "Segoe UI", system-ui, sans-serif; color: #1b1f27; margin: 32px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.meta { color: #6b7380; margin-bottom: 18px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #cfd5de; padding: 6px 10px; text-align: left; vertical-align: top; }
th { background: #eef2f7; }
tbody tr:nth-child(even) { background: #f8fafc; }
td.empty { color: #aab1bd; text-align: center; }
.note { color: #6b7380; margin-top: 14px; }
@media print { body { margin: 10mm; } th { background: #eee !important; } }
"""


def report_html(report: Report, source_name: str, when: str) -> str:
    """The report as one self-contained HTML page (everything is escaped)."""
    e = html.escape
    head = "".join(f"<th>{e(h)}</th>" for h in report.headers)
    body = []
    for row in report.rows:
        cells = "".join(f"<td>{e(c)}</td>" if c else '<td class="empty">&mdash;</td>'
                        for c in row)
        body.append(f"<tr>{cells}</tr>")
    if not body:
        body.append(f'<tr><td class="empty" colspan="{len(report.headers)}">'
                    "Nothing to report</td></tr>")
    note = f'<p class="note">{e(report.note)}</p>' if report.note else ""
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{e(report.title)} – {e(source_name)}</title>\n"
        f"<style>{REPORT_CSS}</style>\n</head>\n<body>\n"
        f"<h1>{e(report.title)}</h1>\n"
        f'<div class="meta">Diagram: {e(source_name)} · {e(when)} · '
        f"{len(report.rows)} row(s)</div>\n"
        f"<table>\n<thead><tr>{head}</tr></thead>\n<tbody>\n" + "\n".join(body) +
        f"\n</tbody>\n</table>\n{note}\n</body>\n</html>\n")


def report_target(path, selected_filter: str = ""):
    """Where and in which format to write a report: (path, 'csv' | 'html').
    The extension typed by the user decides; without a known one the chosen
    filter does, and its extension is appended."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".csv":
        return path, "csv"
    if ext in (".html", ".htm"):
        return path, "html"
    fmt = "csv" if "csv" in selected_filter.lower() else "html"
    return path.with_name(path.name + "." + fmt), fmt


def write_text_atomic(path, text: str, encoding: str) -> None:
    """Write `text` so that an existing file is replaced only on success."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
# reports-end



# attachments-begin  (files and the .bpmn archive, no widgets - see tests)
ARCHIVE_JSON = "diagram.json"          # the diagram inside the tar archive
ARCHIVE_DIR = "attachments"            # attachments/<document id>/<file name>
MAX_JSON_BYTES = 64 * 1024 * 1024      # refuse absurdly large diagram.json files
MAX_NAME_LEN = 120


def safe_filename(name, default: str = "file") -> str:
    """One harmless file name: no folders, no control characters."""
    name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch >= " " and ch != "\x7f").strip()
    name = name.rstrip(". ")
    if not name:
        return default
    if len(name) > MAX_NAME_LEN:
        stem, ext = os.path.splitext(name)
        name = stem[:max(1, MAX_NAME_LEN - len(ext))] + ext
    return name


def unique_name(name: str, taken) -> str:
    """`name`, or "stem (2).ext", "stem (3).ext" ... if `taken` already has it
    (compared case-insensitively, like most file systems do)."""
    low = {t.lower() for t in taken}
    if name.lower() not in low:
        return name
    stem, ext = os.path.splitext(name)
    k = 2
    while f"{stem} ({k}){ext}".lower() in low:
        k += 1
    return f"{stem} ({k}){ext}"


def format_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class Attachment:
    """A file attached to a document. `path` is a private copy of the file in
    the session folder (see AttachmentStore), so the original may change."""

    __slots__ = ("name", "path")

    def __init__(self, name: str, path):
        self.name = name
        self.path = Path(path)

    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0


class AttachmentStore:
    """Session folder holding the attached files until the diagram is saved.
    It only ever deletes files that it created itself."""

    def __init__(self):
        self.root: Path | None = None
        self._count = 0
        atexit.register(self.cleanup)

    def _new_path(self, name: str) -> Path:
        if self.root is None or not self.root.is_dir():
            self.root = Path(tempfile.mkdtemp(prefix="bpmn-files-"))
        self._count += 1
        return self.root / f"{self._count:06d}_{safe_filename(name)}"

    def add_file(self, src, name: str) -> Path:
        """Copy the file `src` into the store under (a safe form of) `name`."""
        dst = self._new_path(name)
        try:
            shutil.copyfile(src, dst)
        except BaseException:
            self.discard(dst)
            raise
        return dst

    def add_stream(self, fileobj, name: str) -> Path:
        dst = self._new_path(name)
        try:
            with open(dst, "wb") as out:
                shutil.copyfileobj(fileobj, out)
        except BaseException:
            self.discard(dst)
            raise
        return dst

    def _owns(self, path) -> bool:
        try:
            return (self.root is not None
                    and Path(path).resolve().parent == self.root.resolve())
        except OSError:
            return False

    def discard(self, path) -> None:
        if self._owns(path):
            try:
                Path(path).unlink()
            except OSError:
                pass

    def cleanup(self) -> None:
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
            self.root = None


def _plain_owner(info):
    """Do not leak user names / ids into the archive."""
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mode = 0o644
    return info


def write_archive(path, data: dict, files: dict) -> None:
    """Write the .bpmn tar archive: diagram.json plus `files`
    (archive member name -> path of the file to store). The target is replaced
    only when everything was written, so a failure cannot damage it."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tarfile.open(tmp, "w", format=tarfile.PAX_FORMAT) as tar:
            payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
            info = tarfile.TarInfo(ARCHIVE_JSON)
            info.size = len(payload)
            info.mtime = int(time.time())
            tar.addfile(_plain_owner(info), io.BytesIO(payload))
            for member, src in files.items():
                tar.add(str(src), arcname=member, recursive=False, filter=_plain_owner)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def referenced_members(data) -> list[str]:
    """Archive members that the diagram's attachment entries point to."""
    found: dict[str, None] = {}
    nodes = data.get("nodes") if isinstance(data, dict) else None
    for nd in nodes if isinstance(nodes, list) else []:
        entries = nd.get("attachments") if isinstance(nd, dict) else None
        for e in entries if isinstance(entries, list) else []:
            f = e.get("file") if isinstance(e, dict) else None
            if (isinstance(f, str) and f.startswith(ARCHIVE_DIR + "/")
                    and posixpath.normpath(f) == f and ".." not in f.split("/")):
                found[f] = None
    return list(found)


def read_archive(path, store: AttachmentStore):
    """Read a .bpmn archive (or a legacy plain-JSON diagram).
    Returns (diagram dict, {archive member name: path of the extracted copy}).

    Nothing is ever extracted to a path taken from the archive: only the
    regular files the diagram refers to are copied, into the private store
    under names the store makes up itself."""
    path = Path(path)
    if not tarfile.is_tarfile(path):
        return json.loads(path.read_text(encoding="utf-8")), {}
    extracted: list[Path] = []
    try:
        with tarfile.open(path, "r:") as tar:
            try:
                member = tar.getmember(ARCHIVE_JSON)
            except KeyError:
                raise ValueError(f"not a diagram archive: {ARCHIVE_JSON} is missing") from None
            if not member.isfile() or member.size > MAX_JSON_BYTES:
                raise ValueError(f"{ARCHIVE_JSON} is not a regular file or is too large")
            f = tar.extractfile(member)
            if f is None:
                raise ValueError(f"{ARCHIVE_JSON} cannot be read")
            with f:
                data = json.loads(f.read().decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"{ARCHIVE_JSON} does not contain a diagram")
            files: dict[str, Path] = {}
            for name in referenced_members(data):
                try:
                    member = tar.getmember(name)
                except KeyError:
                    continue                       # reported as "missing" by load_dict
                src = tar.extractfile(member) if member.isfile() else None
                if src is None:                    # links, devices, folders: ignored
                    continue
                with src:
                    dst = store.add_stream(src, posixpath.basename(name))
                extracted.append(dst)
                files[name] = dst
        return data, files
    except BaseException:
        for p in extracted:
            store.discard(p)
        raise

LINK_SCHEMES = ("http", "https", "ftp", "mailto")   # the only kinds of address we accept / open
MAX_URL_LEN = 2048
MAX_LINK_DESC = 300


class Link:
    """A web address attached to a document, with a short description."""

    __slots__ = ("description", "url")

    def __init__(self, description: str, url: str):
        self.description = description
        self.url = url


def normalize_url(text) -> str:
    """Check an address typed by the user and return it ready to store: an
    address without a scheme ("example.com/x") becomes https://. Raises
    ValueError with a message for the user. Only http, https, ftp and mailto
    are accepted - never file:, javascript: and the like, because the link is
    handed to the operating system when it is opened."""
    url = str(text).strip()
    if not url:
        raise ValueError("Enter the address of the link.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValueError("The address must not contain spaces or control characters.")
    if len(url) > MAX_URL_LEN:
        raise ValueError(f"The address is too long (more than {MAX_URL_LEN} characters).")
    if "://" not in url and not url.lower().startswith("mailto:"):
        url = "https://" + url
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port                                   # raises ValueError if it is not a number
    except ValueError:
        raise ValueError("This is not a valid address.") from None
    scheme = parts.scheme.lower()
    if scheme not in LINK_SCHEMES:
        raise ValueError("Only http, https, ftp and mailto addresses are supported.")
    if scheme == "mailto":
        if not parts.path:
            raise ValueError("The e-mail address is missing.")
    elif not parts.hostname:
        raise ValueError("The address has no host name.")
    return url


def link_text(link: Link) -> str:
    """How a link is listed next to the attached files."""
    return (f"Link: {link.description}    ({link.url})" if link.description
            else f"Link: {link.url}")
# attachments-end


# --------------------------------------------------------------------------- #
# Diagram nodes
# --------------------------------------------------------------------------- #
class NodeItem(QGraphicsItem):
    """Base class of all primitives: a movable, labelled box."""

    KIND = "node"
    FILL = C_PROCESS_FILL
    DEFAULT_SIZE = (140, 80)
    NAME = "item"
    IS_DOC = False        # documents link to processes, everything else to documents
    RESIZABLE = True
    CONNECTABLE = True    # False: connections to or from it are refused (text comment)
    SNAP = GRID           # position snaps to multiples of this (see ExternalItem)

    def __init__(self, x: float, y: float, w: float, h: float, text: str = ""):
        super().__init__()
        self._rect = QRectF(0, 0, w, h)
        self.text = text
        self.connections: list[ConnectionItem] = []
        self.hint: str | None = None          # None | "source" | "target"
        self._active_handle: str | None = None
        self._press_pos = QPointF()
        self._changed_by_mouse = False

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self.setPos(x, y)

    # ---- geometry --------------------------------------------------------- #
    def boundingRect(self) -> QRectF:
        m = HANDLE
        return self._rect.adjusted(-m, -m, m, m)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        m = HANDLE / 2
        path.addRect(self._rect.adjusted(-m, -m, m, m))
        return path

    def scene_rect(self) -> QRectF:
        return self.mapRectToScene(self._rect)

    def usable_span(self, side: str) -> tuple[float, float]:
        """Scene-coordinate range along `side` ('l','r','t','b') where a
        connection may attach (y-range for l/r, x-range for t/b)."""
        r = self.scene_rect()
        if side in ("l", "r"):
            return r.top(), r.bottom()
        return r.left(), r.right()

    def can_accept_connection(self) -> bool:
        return True

    def refresh_geometry(self) -> None:
        """Called when the name or the connections changed."""
        self.update()

    def port_count(self) -> int:
        """Number of connections on the busier of the two borders."""
        out = sum(1 for c in self.connections if c.source is self)
        return max(out, len(self.connections) - out)

    def port_margin(self) -> float:
        return 0.0

    def min_height(self) -> float:
        """Smallest height that leaves PORT_GAP between all attachment points."""
        return max(MIN_H, self.port_count() * PORT_GAP + self.port_margin())

    def ensure_ports_fit(self, snap: bool = True) -> None:
        need = self.min_height()
        if self._rect.height() < need:
            if snap:
                need = math.ceil(need / GRID) * GRID
            self.prepareGeometryChange()
            self._rect.setHeight(need)
            self.update()

    def display_name(self) -> str:
        label = " ".join(self.text.split())
        return f"{self.NAME} '{label}'" if label else f"unnamed {self.NAME}"

    # ---- resize handles --------------------------------------------------- #
    def _handle_points(self) -> dict[str, QPointF]:
        r = self._rect
        cx, cy = r.center().x(), r.center().y()
        return {
            "tl": r.topLeft(), "tr": r.topRight(),
            "br": r.bottomRight(), "bl": r.bottomLeft(),
            "t": QPointF(cx, r.top()), "b": QPointF(cx, r.bottom()),
            "l": QPointF(r.left(), cy), "r": QPointF(r.right(), cy),
        }

    def handle_at(self, pos: QPointF) -> str | None:
        if not self.isSelected() or not self.RESIZABLE:
            return None
        s = HANDLE_HIT
        for name, p in self._handle_points().items():
            if QRectF(p.x() - s / 2, p.y() - s / 2, s, s).contains(pos):
                return name
        return None

    def _resize_to(self, scene_pos: QPointF) -> None:
        sc = self.scene()
        if sc is not None:
            scene_pos = sc.snap_point(scene_pos)
        p = self.mapFromScene(scene_pos)
        r = QRectF(self._rect)
        h = self._active_handle or ""
        if "l" in h:
            r.setLeft(min(p.x(), r.right() - MIN_W))
        if "r" in h:
            r.setRight(max(p.x(), r.left() + MIN_W))
        mh = self.min_height()
        if "t" in h:
            r.setTop(min(p.y(), r.bottom() - mh))
        if "b" in h:
            r.setBottom(max(p.y(), r.top() + mh))
        if r == self._rect:
            return
        self.prepareGeometryChange()
        self._rect = r
        self.update()
        if sc is not None:
            sc.relayout()

    # ---- painting --------------------------------------------------------- #
    def draw_body(self, painter: QPainter) -> None:  # overridden
        painter.drawRect(self._rect)

    def text_rect(self) -> QRectF:
        return self._rect.adjusted(10, 10, -10, -10)

    def draw_label(self, painter: QPainter) -> None:
        """The name, centred inside the shape."""
        painter.save()
        painter.setClipRect(self.text_rect())
        painter.setPen(C_TEXT)
        opt = QTextOption(Qt.AlignmentFlag.AlignCenter)
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        painter.drawText(self.text_rect(), self.text, opt)
        painter.restore()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isSelected():
            pen = QPen(C_ACCENT, 2.5)
        elif self.hint == "source":
            pen = QPen(C_SOURCE, 3)
        elif self.hint == "target":
            pen = QPen(C_TARGET, 2.5, Qt.PenStyle.DashLine)
        else:
            pen = QPen(C_OUTLINE, 1.6)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(self.FILL)
        self.draw_body(painter)

        self.draw_label(painter)

        if self.isSelected() and self.RESIZABLE:
            painter.setPen(QPen(C_ACCENT, 1.5))
            painter.setBrush(Qt.GlobalColor.white)
            for p in self._handle_points().values():
                painter.drawRect(QRectF(p.x() - HANDLE / 2, p.y() - HANDLE / 2,
                                        HANDLE, HANDLE))

    # ---- interaction ------------------------------------------------------ #
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            sc = self.scene()
            if sc is not None and isinstance(value, QPointF):
                return sc.snap_point(value, self.SNAP)
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            sc = self.scene()
            if sc is not None:
                sc.relayout()
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.update()
        return super().itemChange(change, value)

    def hoverMoveEvent(self, event) -> None:
        sc = self.scene()
        shape = Qt.CursorShape.ArrowCursor
        if sc is not None and sc.mode == MODE_SELECT:
            h = self.handle_at(event.pos())
            if h:
                shape = HANDLE_CURSORS[h]
        self.setCursor(QCursor(shape))
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            h = self.handle_at(event.pos())
            if h:
                self._active_handle = h
                self._changed_by_mouse = False
                event.accept()
                return
            self._press_pos = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._active_handle:
            self._changed_by_mouse = True
            self._resize_to(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        changed = False
        if self._active_handle:
            changed = self._changed_by_mouse
            self._active_handle = None
        else:
            changed = self.pos() != self._press_pos
        super().mouseReleaseEvent(event)
        if changed and self.scene() is not None:
            self.scene().touch()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.edit_text()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def edit_text(self) -> None:
        sc = self.scene()
        views = sc.views() if sc else []
        text, ok = QInputDialog.getText(
            views[0] if views else None, f"Name of {self.NAME}",
            f"Enter the name of this {self.NAME}:",
            QLineEdit.EchoMode.Normal, " ".join(self.text.split()))
        text = text.strip()
        if ok and text != self.text:
            self.text = text
            self.refresh_geometry()
            if sc:
                sc.touch()

    # ---- (de)serialisation ------------------------------------------------ #
    def to_dict(self, node_id: int, ids: dict | None = None,
                files: dict | None = None) -> dict:
        r = self.scene_rect()
        return {"id": node_id, "type": self.KIND, "text": self.text,
                "x": r.x(), "y": r.y(), "w": r.width(), "h": r.height()}


class ProcessItem(NodeItem):
    KIND = PROCESS
    NAME = "process"
    FILL = C_PROCESS_FILL
    DEFAULT_SIZE = (140, 80)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.table: list[TableSet] = []       # shown in the panel under the diagram

    def input_docs(self) -> list:
        return linked_docs(self, True)

    def output_docs(self) -> list:
        return linked_docs(self, False)

    def sanitize_table(self) -> bool:
        return sanitize_sets(self.table, self.input_docs(), self.output_docs())

    def to_dict(self, node_id: int, ids: dict | None = None,
                files: dict | None = None) -> dict:
        d = super().to_dict(node_id, ids, files)
        if self.table and ids is not None:
            d["table"] = sets_to_list(self.table, ids)
        return d


def paperclip_path() -> QPainterPath:
    """A paper clip in a 10 x 17 box (y points down): three nested bends."""
    p = QPainterPath(QPointF(9, 13))
    p.lineTo(9, 4.5)
    p.arcTo(QRectF(1, 0.5, 8, 8), 0, 180)       # big bend at the top
    p.lineTo(1, 14)
    p.arcTo(QRectF(1, 11, 6, 6), 180, 180)      # bend at the bottom
    p.lineTo(7, 6.5)
    p.arcTo(QRectF(3, 4.5, 4, 4), 0, 180)       # small bend inside
    p.lineTo(3, 12.5)
    return p


class DocumentItem(NodeItem):
    IS_DOC = True
    KIND = DOCUMENT
    NAME = "document"
    FILL = C_DOC_FILL
    DEFAULT_SIZE = (120, 80)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attachments: list[Attachment] = []   # listed in the panel under the diagram
        self.links: list[Link] = []               # ... together with the web links

    def attach(self, src, store: AttachmentStore) -> Attachment:
        """Attach a copy of the file `src` (raises OSError if it cannot be read)."""
        name = unique_name(safe_filename(Path(src).name),
                           [a.name for a in self.attachments])
        att = Attachment(name, store.add_file(src, name))
        self.attachments.append(att)
        self.attachments_changed()
        return att

    def detach(self, index: int, store: AttachmentStore) -> None:
        att = self.attachments.pop(index)
        store.discard(att.path)
        self.attachments_changed()

    def add_link(self, description: str, url: str) -> Link:
        link = Link(description, url)
        self.links.append(link)
        self.attachments_changed()
        return link

    def set_link(self, index: int, description: str, url: str) -> None:
        self.links[index].description = description
        self.links[index].url = url
        self.attachments_changed()

    def remove_link(self, index: int) -> None:
        del self.links[index]
        self.attachments_changed()

    def attachments_changed(self) -> None:
        n, m = len(self.attachments), len(self.links)
        parts = ([f"{n} attached file{'' if n == 1 else 's'}"] if n else []) + \
                ([f"{m} link{'' if m == 1 else 's'}"] if m else [])
        self.setToolTip(", ".join(parts))
        self.update()

    def draw_label(self, painter: QPainter) -> None:
        super().draw_label(painter)
        if self.attachments or self.links:         # paper clip, lower right corner
            r = self._rect
            painter.save()
            painter.translate(r.right() - 17, r.bottom() - 22)
            pen = QPen(QColor("#4a5568"), 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(paperclip_path())
            painter.restore()

    def to_dict(self, node_id: int, ids: dict | None = None,
                files: dict | None = None) -> dict:
        d = super().to_dict(node_id, ids, files)
        if self.attachments:
            entries = []
            for a in self.attachments:
                member = f"{ARCHIVE_DIR}/{node_id}/{a.name}"
                entries.append({"name": a.name, "file": member})
                if files is not None:
                    files[member] = a.path
            d["attachments"] = entries
        if self.links:
            d["links"] = [{"description": k.description, "url": k.url} for k in self.links]
        return d

    def ear(self) -> float:
        return min(EAR, self._rect.width() / 3, self._rect.height() / 3)

    def draw_body(self, painter: QPainter) -> None:
        r, e = self._rect, self.ear()
        outline = QPolygonF([
            QPointF(r.left() + e, r.top()), r.topRight(),
            r.bottomRight(), r.bottomLeft(), QPointF(r.left(), r.top() + e),
        ])
        painter.drawPolygon(outline)
        fold = QPolygonF([
            QPointF(r.left() + e, r.top()),
            QPointF(r.left() + e, r.top() + e),
            QPointF(r.left(), r.top() + e),
        ])
        painter.setBrush(C_DOC_FOLD)
        painter.drawPolygon(fold)

    def usable_span(self, side: str) -> tuple[float, float]:
        # The dog-ear cuts away the first `ear` px of the left and top sides.
        lo, hi = super().usable_span(side)
        if side in ("l", "t"):
            lo += self.ear()
        return lo, hi

    def port_margin(self) -> float:
        return EAR                    # the dog-ear takes up room on the left border


CAPTION_GAP = 6.0     # distance between an external process and its name


class ExternalItem(NodeItem):
    """Link to an external process: a small gray square with ONE connection.

    The name is written beside the square on the side opposite to the port:
    to the left, right-aligned, when the connection leaves the item (the port
    is on the right) and to the right, left-aligned, when it enters (port on
    the left). Before it is connected the name is shown on the right.
    """

    KIND = EXTERNAL
    NAME = "external process"
    FILL = C_EXTERNAL_FILL
    SIZE = 20                          # the port sits at its centre
    DEFAULT_SIZE = (SIZE, SIZE)
    RESIZABLE = False
    SNAP = GRID / 2                    # snaps to half of the grid size

    def __init__(self, x: float, y: float, w: float = SIZE, h: float = SIZE,
                 text: str = ""):
        super().__init__(x, y, self.SIZE, self.SIZE, text)   # size is fixed

    def min_height(self) -> float:
        return float(self.SIZE)

    def ensure_ports_fit(self, snap: bool = True) -> None:
        pass                           # never grows

    def can_accept_connection(self) -> bool:
        return not self.connections

    def refresh_geometry(self) -> None:
        self.prepareGeometryChange()   # the caption is part of the bounding rect
        self.update()

    def sends(self) -> bool:
        """True when its connection leaves it (port on the right border)."""
        return bool(self.connections) and self.connections[0].source is self

    def caption_rect(self) -> QRectF:
        label = " ".join(self.text.split())
        if not label:
            return QRectF()
        fm = QFontMetricsF(QApplication.font())
        w, h = fm.horizontalAdvance(label) + 2, fm.height()
        y = (self._rect.height() - h) / 2
        x = -CAPTION_GAP - w if self.sends() else self._rect.width() + CAPTION_GAP
        return QRectF(x, y, w, h)

    def boundingRect(self) -> QRectF:
        r = super().boundingRect()
        c = self.caption_rect()
        return r.united(c.adjusted(-2, -2, 2, 2)) if not c.isEmpty() else r

    def shape(self) -> QPainterPath:
        path = super().shape()
        c = self.caption_rect()
        if not c.isEmpty():
            path.addRect(c)            # the name can be clicked, too
        return path

    def draw_label(self, painter: QPainter) -> None:
        c = self.caption_rect()
        if c.isEmpty():
            return
        align = Qt.AlignmentFlag.AlignRight if self.sends() else Qt.AlignmentFlag.AlignLeft
        opt = QTextOption(align | Qt.AlignmentFlag.AlignVCenter)
        opt.setWrapMode(QTextOption.WrapMode.NoWrap)
        painter.save()
        painter.setFont(QApplication.font())
        painter.setPen(C_TEXT)
        painter.drawText(c, " ".join(self.text.split()), opt)
        painter.restore()


class CommentItem(NodeItem):
    """A text comment: just a line of text. No border, no fill, no resize
    handles and no connections. The size follows the text, which can never be
    empty - an empty text is replaced by "Undef", so the item cannot vanish."""

    KIND = COMMENT
    NAME = "text comment"
    DEFAULT_SIZE = (60, 24)
    RESIZABLE = False
    CONNECTABLE = False
    SNAP = GRID / 2
    PAD = 3.0                          # space around the text (the clickable area)

    def __init__(self, x: float, y: float, w: float = 0, h: float = 0,
                 text: str = ""):
        super().__init__(x, y, 1, 1, text)      # the real size comes from the text

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value) -> None:
        self._text = comment_text(value)
        self._fit()

    def _fit(self) -> None:
        fm = QFontMetricsF(QApplication.font())
        w = math.ceil(fm.horizontalAdvance(self._text)) + 2 * self.PAD
        h = math.ceil(fm.height()) + 2 * self.PAD
        self.prepareGeometryChange()
        self._rect = QRectF(0, 0, w, h)
        self.update()

    def can_accept_connection(self) -> bool:
        return False

    def min_height(self) -> float:
        return self._rect.height()

    def ensure_ports_fit(self, snap: bool = True) -> None:
        pass                           # has no ports

    def refresh_geometry(self) -> None:
        self._fit()

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-2, -2, 2, 2)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self._rect.adjusted(-2, -2, 2, 2))
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isSelected():          # no border of its own: only mark the selection
            painter.setPen(QPen(C_ACCENT, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._rect.adjusted(-1, -1, 1, 1))
        opt = QTextOption(Qt.AlignmentFlag.AlignCenter)
        opt.setWrapMode(QTextOption.WrapMode.NoWrap)
        painter.setFont(QApplication.font())
        painter.setPen(C_TEXT)
        painter.drawText(self._rect, self._text, opt)

    def edit_text(self) -> None:
        sc = self.scene()
        views = sc.views() if sc else []
        text, ok = QInputDialog.getText(
            views[0] if views else None, "Text comment",
            f"Enter the text of this comment (an empty text becomes \u201c{UNDEF_TEXT}\u201d):",
            QLineEdit.EchoMode.Normal, self._text)
        if not ok:
            return
        new = comment_text(text)
        if new != self._text:
            self.text = new
            if sc:
                sc.touch()


NODE_CLASSES = {PROCESS: ProcessItem, DOCUMENT: DocumentItem, EXTERNAL: ExternalItem,
                COMMENT: CommentItem}


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #
_SEQ = itertools.count(1)


class ConnectionItem(QGraphicsPathItem):
    """Directed arrow source -> target. Always joins one process and one document.

    The route is computed by layout_connections(). When the connection is
    selected it shows handles: round ones slide an end point along the border
    of its item, square ones move a segment of the line.
    """

    def __init__(self, source: NodeItem, target: NodeItem):
        super().__init__()
        self.source = source
        self.target = target
        self.seq = next(_SEQ)                 # creation order (stable layout)
        self.src_t: float | None = None       # manual port position (0..1) or auto
        self.dst_t: float | None = None
        self.offsets: dict[str, float] = {}   # manual lane offsets (see build_route)
        self.case: str | None = None
        self.y1 = self.y2 = 0.0
        self.route: Route | None = None
        self._line = QPainterPath()
        self._arrow = QPolygonF()
        self._active: str | None = None       # handle being dragged
        self.setZValue(0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        source.connections.append(self)
        target.connections.append(self)

    @property
    def is_output(self) -> bool:
        """True when the arrow leaves a process (document is its output)."""
        return not self.source.IS_DOC

    def is_customised(self) -> bool:
        return bool(self.offsets) or self.src_t is not None or self.dst_t is not None

    def clear_customisation(self) -> None:
        self.src_t = self.dst_t = None
        self.offsets.clear()

    # ---- geometry ---------------------------------------------------------- #
    def apply_route(self) -> None:
        """Rebuild the drawn path from self.route."""
        line, arrow = QPainterPath(), QPolygonF()
        pts = self.route.pts if self.route is not None else []
        if len(pts) >= 2:
            line.moveTo(pts[0])
            for p in pts[1:]:
                line.lineTo(p)
            tip, prev = pts[-1], pts[-2]
            length = math.hypot(tip.x() - prev.x(), tip.y() - prev.y())
            if length > 0:
                ux, uy = (tip.x() - prev.x()) / length, (tip.y() - prev.y()) / length
                half = 5.0
                base = QPointF(tip.x() - ux * ARROW_LEN, tip.y() - uy * ARROW_LEN)
                arrow = QPolygonF([
                    tip,
                    QPointF(base.x() - uy * half, base.y() + ux * half),
                    QPointF(base.x() + uy * half, base.y() - ux * half),
                ])
        self._line = line
        self._arrow = arrow
        combined = QPainterPath(line)
        if not arrow.isEmpty():
            combined.addPolygon(arrow)
            combined.closeSubpath()
        self.setPath(combined)
        self.update()

    def boundingRect(self) -> QRectF:
        return self.path().boundingRect().adjusted(-HANDLE, -HANDLE, HANDLE, HANDLE)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        shape = stroker.createStroke(self.path())
        if self.isSelected() and self.route is not None:
            s = HANDLE_HIT
            for _key, p in self.route.handles:
                shape.addRect(QRectF(p.x() - s / 2, p.y() - s / 2, s, s))
        return shape

    def handle_at(self, pos: QPointF) -> str | None:
        if not self.isSelected() or self.route is None:
            return None
        s = HANDLE_HIT
        for key, p in self.route.handles:        # end points come first
            if QRectF(p.x() - s / 2, p.y() - s / 2, s, s).contains(pos):
                return key
        return None

    # ---- painting ---------------------------------------------------------- #
    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isSelected()
        color = C_ACCENT if selected else C_ARROW
        pen = QPen(color, 2.4 if selected else 1.8)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)       # polyline must not be filled
        painter.drawPath(self._line)
        handles = self.route.handles if (selected and self.route) else []
        hpen = QPen(C_ACCENT, 1.5)
        for key, p in handles:                        # round: end points (under the arrow)
            if key in END_KEYS:
                painter.setPen(hpen)
                painter.setBrush(Qt.GlobalColor.white)
                painter.drawEllipse(p, HANDLE / 2 + 1, HANDLE / 2 + 1)
        painter.setPen(pen)
        painter.setBrush(color)
        painter.drawPolygon(self._arrow)
        for key, p in handles:                        # square: segments
            if key not in END_KEYS:
                painter.setPen(hpen)
                painter.setBrush(Qt.GlobalColor.white)
                painter.drawRect(QRectF(p.x() - HANDLE / 2, p.y() - HANDLE / 2,
                                        HANDLE, HANDLE))

    # ---- interaction ------------------------------------------------------- #
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            # a selected connection sits above the items so its handles can be
            # grabbed even where they overlap an item's border
            self.setZValue(2 if bool(value) else 0)
            self.update()
        return super().itemChange(change, value)

    def hoverMoveEvent(self, event) -> None:
        sc = self.scene()
        if sc is None or sc.mode != MODE_SELECT:
            self.unsetCursor()                    # keep the tool's crosshair
        else:
            shape = Qt.CursorShape.ArrowCursor
            key = self.handle_at(event.pos())
            if key in ("src", "dst", "mid"):
                shape = Qt.CursorShape.SizeVerCursor
            elif key:
                shape = Qt.CursorShape.SizeHorCursor
            self.setCursor(QCursor(shape))
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            key = self.handle_at(event.pos())
            if key:
                self._active = key
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._active:
            sc = self.scene()
            if sc is not None:
                sc.drag_connection_handle(self, self._active, event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._active:
            self._active = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        sc = self.scene()
        if event.button() == Qt.MouseButton.LeftButton and sc is not None:
            sc.reset_connection_routes([self])
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    # ---- (de)serialisation -------------------------------------------------- #
    def to_dict(self, ids: dict) -> dict:
        d = {"source": ids[id(self.source)], "target": ids[id(self.target)]}
        if self.src_t is not None:
            d["src_t"] = round(self.src_t, 4)
        if self.dst_t is not None:
            d["dst_t"] = round(self.dst_t, 4)
        if self.offsets:
            d["offsets"] = {k: round(v, 2) for k, v in self.offsets.items()}
        return d

    def load_custom(self, d: dict) -> None:
        """Restore manual routing from a saved connection (all keys optional)."""
        if d.get("src_t") is not None:
            self.src_t = float(d["src_t"])
        if d.get("dst_t") is not None:
            self.dst_t = float(d["dst_t"])
        for k, v in (d.get("offsets") or {}).items():
            if k in ("lane", "out", "mid", "in"):
                self.offsets[k] = float(v)


# --------------------------------------------------------------------------- #
# Scene (all editing logic lives here)
# --------------------------------------------------------------------------- #
class DiagramScene(QGraphicsScene):
    modeChanged = Signal(str)
    message = Signal(str, bool)       # text, is_error
    dirtyChanged = Signal(bool)
    contentChanged = Signal()         # anything in the diagram changed
    rolesChanged = Signal()           # the roles dictionary changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-3000, -3000, 6000, 6000)
        self.mode = MODE_SELECT
        self.snap = True
        self.show_grid = True
        self.exporting = False
        self.dirty = False
        self.store = AttachmentStore()      # private copies of the attached files
        self.roles = RoleDictionary()       # saved in the .bpmn file
        self._pending: NodeItem | None = None
        self._rubber: QGraphicsPathItem | None = None
        self._press_scene_pos = QPointF()

    # ---- helpers ---------------------------------------------------------- #
    def snap_point(self, p: QPointF, step: float = GRID) -> QPointF:
        """Snap `p` to a multiple of `step` (the grid size unless told otherwise)."""
        if not self.snap:
            return QPointF(p)
        return QPointF(round(p.x() / step) * step, round(p.y() / step) * step)

    def nodes(self) -> list[NodeItem]:
        return [i for i in self.items() if isinstance(i, NodeItem)]

    def connection_items(self) -> list[ConnectionItem]:
        return [i for i in self.items() if isinstance(i, ConnectionItem)]

    def node_at(self, pos: QPointF) -> NodeItem | None:
        for it in self.items(pos):
            if isinstance(it, NodeItem):
                return it
        return None

    def touch(self) -> None:
        self.set_dirty(True)
        self.contentChanged.emit()

    # ---- roles dictionary (the Roles window and the process tables use these) -- #
    def _table_sets(self):
        for node in self.nodes():
            if isinstance(node, ProcessItem):
                yield from node.table

    def roles_touch(self) -> None:
        self.set_dirty(True)
        self.rolesChanged.emit()

    def role_usage(self, name: str) -> int:
        """In how many process-table sets the role is chosen."""
        return sum(1 for st in self._table_sets() if st.role == name)

    def add_role(self, name: str = "") -> Role:
        role = self.roles.add(name)
        self.roles_touch()
        return role

    def rename_role(self, old: str, new: str) -> str:
        used = self.roles.rename(old, new)       # raises ValueError
        if used != old:
            for st in self._table_sets():
                if st.role == old:
                    st.role = used
        self.roles_touch()
        return used

    def delete_role(self, name: str) -> None:
        self.roles.remove(name)
        for st in self._table_sets():
            if st.role == name:
                st.role = ""
        self.roles_touch()

    def set_role_description(self, name: str, text: str) -> None:
        role = self.roles.find(name)
        if role is not None and role.description != text:
            role.description = text
            self.roles_touch()

    def set_role_members(self, name: str, users, roles) -> None:
        self.roles.set_members(name, users, roles)   # raises ValueError
        self.roles_touch()

    def set_dirty(self, value: bool) -> None:
        if value != self.dirty:
            self.dirty = value
            self.dirtyChanged.emit(value)

    # ---- modes ------------------------------------------------------------ #
    def set_mode(self, mode: str) -> None:
        self.cancel_pending()
        self.mode = mode
        if mode != MODE_SELECT:
            self.clearSelection()
        for view in self.views():
            if mode == MODE_SELECT:
                view.viewport().unsetCursor()
            else:
                view.viewport().setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.modeChanged.emit(mode)

    # ---- creating / deleting ---------------------------------------------- #
    def add_node(self, kind: str, center: QPointF, text: str = "") -> NodeItem:
        cls = NODE_CLASSES[kind]
        w, h = cls.DEFAULT_SIZE
        item = cls(0, 0, w, h, text)
        size = item._rect                     # (a comment is sized by its text)
        item.setPos(self.snap_point(QPointF(center.x() - size.width() / 2,
                                            center.y() - size.height() / 2), cls.SNAP))
        self.addItem(item)
        self.clearSelection()
        item.setSelected(True)
        self.touch()
        return item

    def connect_nodes(self, a: NodeItem, b: NodeItem) -> ConnectionItem | None:
        """Validate and create a connection a -> b. Reports problems via `message`."""
        if a is b:
            return None
        for node in (a, b):
            if not node.CONNECTABLE:
                self.message.emit(f"A {node.NAME} cannot be connected to anything.", True)
                return None
        if a.IS_DOC == b.IS_DOC:
            if a.IS_DOC:
                msg = ("Documents cannot be connected to each other - "
                       "a document can only link to a process.")
            else:
                msg = ("Processes cannot be connected directly - "
                       "connect them through a document.")
            self.message.emit(msg, True)
            return None
        for node in (a, b):
            if not node.can_accept_connection():
                self.message.emit(f"The {node.display_name()} already has its "
                                  "only connection.", True)
                return None
        for c in a.connections:
            if c.source is a and c.target is b:
                self.message.emit("These two items are already connected "
                                  "in this direction.", True)
                return None
        conn = ConnectionItem(a, b)
        self.addItem(conn)
        for node in (a, b):
            node.ensure_ports_fit(self.snap)     # room for one more attachment point
            node.refresh_geometry()
        self.relayout()
        self.touch()
        kind = "Output" if conn.is_output else "Input"
        self.message.emit(f"{kind} added: {a.display_name()} \u2192 "
                          f"{b.display_name()}", False)
        return conn

    def remove_connection(self, conn: ConnectionItem) -> None:
        for node in (conn.source, conn.target):
            if conn in node.connections:
                node.connections.remove(conn)
                node.refresh_geometry()          # e.g. an external's name side
            if isinstance(node, ProcessItem):
                node.sanitize_table()            # forget the document that was unlinked
        if conn.scene() is self:
            self.removeItem(conn)

    def delete_selected(self) -> None:
        self.cancel_pending()
        items = self.selectedItems()
        if not items:
            return
        nodes = [i for i in items if isinstance(i, NodeItem)]
        conns = {id(i): i for i in items if isinstance(i, ConnectionItem)}
        for n in nodes:
            for c in n.connections:
                conns[id(c)] = c
        for c in conns.values():
            self.remove_connection(c)
        for n in nodes:
            self.removeItem(n)
            self.discard_attachments(n)
        self.relayout()
        self.touch()

    def discard_attachments(self, node) -> None:
        """Delete the private copies of the files attached to a removed node."""
        if isinstance(node, DocumentItem):
            for a in node.attachments:
                self.store.discard(a.path)
            node.attachments = []

    def edit_selected_label(self) -> None:
        sel = [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        if len(sel) == 1:
            sel[0].edit_text()

    # ---- connection layout --------------------------------------------------- #
    def relayout(self) -> None:
        """Recompute ports and routes of every connection."""
        conns = self.connection_items()
        if not conns:
            return
        layout_connections(conns)
        for c in conns:
            c.apply_route()

    def drag_connection_handle(self, conn: ConnectionItem, key: str,
                               pos: QPointF) -> bool:
        others = [o for o in self.connection_items() if o is not conn]
        if not move_handle(conn, key, pos.x(), pos.y(), others, self.snap):
            return False
        self.relayout()
        self.touch()
        return True

    def reset_connection_routes(self, conns) -> None:
        changed = [c for c in conns if c.is_customised()]
        for c in changed:
            c.clear_customisation()
        if changed:
            self.relayout()
            self.touch()
            self.message.emit("Connection routing reset to automatic.", False)

    def reset_selected_routes(self) -> None:
        conns = {}
        for it in self.selectedItems():
            if isinstance(it, ConnectionItem):
                conns[id(it)] = it
            elif isinstance(it, NodeItem):
                for c in it.connections:
                    conns[id(c)] = c
        self.reset_connection_routes(list(conns.values()))

    # ---- pending connection (rubber band) ---------------------------------- #
    def begin_connect(self, node: NodeItem, pos: QPointF) -> None:
        if not node.CONNECTABLE:
            self.message.emit(f"A {node.NAME} cannot be connected to anything.", True)
            return
        if not node.can_accept_connection():
            self.message.emit(f"The {node.display_name()} already has its "
                              "only connection.", True)
            return
        self._pending = node
        self._press_scene_pos = QPointF(pos)
        node.hint = "source"
        for n in self.nodes():
            if n.IS_DOC != node.IS_DOC and n.can_accept_connection():
                n.hint = "target"
            n.update()
        line = QGraphicsPathItem()
        line.setPen(QPen(C_SOURCE, 2, Qt.PenStyle.DashLine))
        line.setZValue(10)
        line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.addItem(line)
        self._rubber = line
        self._update_rubber(pos)
        self.message.emit(
            "Now choose a process or an external process." if node.IS_DOC
            else "Now choose a document.", False)

    def _update_rubber(self, pos: QPointF) -> None:
        if self._pending is None or self._rubber is None:
            return
        r = self._pending.scene_rect()
        start = QPointF(r.right(), r.center().y())          # arrows leave on the right
        mx = (start.x() + pos.x()) / 2 if pos.x() > start.x() + MIN_FWD_GAP \
            else start.x() + STUB
        path = QPainterPath(start)
        path.lineTo(mx, start.y())
        path.lineTo(mx, pos.y())
        path.lineTo(pos)
        self._rubber.setPath(path)

    def cancel_pending(self) -> None:
        if self._rubber is not None:
            self.removeItem(self._rubber)
            self._rubber = None
        if self._pending is not None:
            self._pending = None
            for n in self.nodes():
                n.hint = None
                n.update()

    # ---- mouse / keyboard -------------------------------------------------- #
    def mousePressEvent(self, event) -> None:
        if self.mode == MODE_SELECT:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.cancel_pending()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.scenePos()
        if self.mode in (MODE_PROCESS, MODE_DOCUMENT, MODE_EXTERNAL, MODE_COMMENT):
            item = self.add_node(
                {MODE_PROCESS: PROCESS, MODE_DOCUMENT: DOCUMENT,
                 MODE_EXTERNAL: EXTERNAL, MODE_COMMENT: COMMENT}[self.mode], pos)
            self.set_mode(MODE_SELECT)
            item.edit_text()          # ask for the name straight away
        elif self.mode == MODE_CONNECT:
            node = self.node_at(pos)
            if node is None:
                self.cancel_pending()
            elif self._pending is None:
                self.begin_connect(node, pos)
            elif node is not self._pending:
                src = self._pending
                self.cancel_pending()
                self.connect_nodes(src, node)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.mode == MODE_CONNECT and self._pending and self._rubber:
            self._update_rubber(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.mode == MODE_SELECT:
            super().mouseReleaseEvent(event)
            return
        if (self.mode == MODE_CONNECT and self._pending
                and event.button() == Qt.MouseButton.LeftButton):
            pos = event.scenePos()
            node = self.node_at(pos)
            dragged = QLineF(self._press_scene_pos, pos).length() > 6
            if node is not None and node is not self._pending:
                src = self._pending
                self.cancel_pending()
                self.connect_nodes(src, node)
            elif node is None and dragged:
                self.cancel_pending()      # dropped on empty canvas -> cancel
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self.mode == MODE_SELECT:
            super().mouseDoubleClickEvent(event)
        else:
            self.mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            if self._pending is not None:
                self.cancel_pending()
            else:
                self.set_mode(MODE_SELECT)
            event.accept()
            return
        super().keyPressEvent(event)

    # ---- background grid --------------------------------------------------- #
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#ffffff"))
        if not self.show_grid or self.exporting:
            return
        if painter.worldTransform().m11() * GRID < 6:      # too dense when zoomed out
            return
        lines = []
        x = math.floor(rect.left() / GRID) * GRID
        while x <= rect.right():
            lines.append(QLineF(x, rect.top(), x, rect.bottom()))
            x += GRID
        y = math.floor(rect.top() / GRID) * GRID
        while y <= rect.bottom():
            lines.append(QLineF(rect.left(), y, rect.right(), y))
            y += GRID
        painter.setPen(QPen(QColor("#e6e9ee"), 0))
        painter.drawLines(lines)

    # ---- persistence ------------------------------------------------------- #
    def to_dict(self, files: dict | None = None) -> dict:
        """The diagram as plain data. If `files` is given, it receives
        {archive member name: file to store} for every attachment."""
        nodes = sorted(self.nodes(),
                       key=lambda n: (n.scenePos().y(), n.scenePos().x()))
        ids = {id(n): i for i, n in enumerate(nodes, 1)}
        conns = sorted(self.connection_items(),
                       key=lambda c: (ids[id(c.source)], ids[id(c.target)]))
        return {
            "version": 2,
            "nodes": [n.to_dict(ids[id(n)], ids, files) for n in nodes],
            "connections": [c.to_dict(ids) for c in conns],
            "roles": self.roles.to_list(),
        }

    def load_dict(self, data: dict, files: dict | None = None) -> int:
        """Replace the diagram. `files` maps archive member names to the
        extracted copies of the attachments. Returns how many attachments the
        diagram lists that are missing from `files`."""
        files = files or {}
        by_id: dict = {}
        for nd in data["nodes"]:
            cls = NODE_CLASSES.get(nd["type"])
            if cls is None:
                raise ValueError(f"Unknown node type: {nd['type']!r}")
            by_id[nd["id"]] = cls(
                float(nd["x"]), float(nd["y"]),
                max(MIN_W, float(nd["w"])), max(MIN_H, float(nd["h"])),
                str(nd.get("text", "")))
        conns = []
        for cd in data.get("connections", []):
            a, b = by_id[cd["source"]], by_id[cd["target"]]
            if not (a.CONNECTABLE and b.CONNECTABLE):
                raise ValueError("File contains a connection to a text comment.")
            if a.IS_DOC == b.IS_DOC:
                raise ValueError("File contains an illegal connection between "
                                 f"two {a.KIND}s.")
            for n in (a, b):
                if not n.can_accept_connection():
                    raise ValueError("File contains an external process with "
                                     "more than one connection.")
            conn = ConnectionItem(a, b)
            conn.load_custom(cd)
            conns.append(conn)
        for nd in data["nodes"]:                 # process tables (links need the connections)
            node = by_id[nd["id"]]
            if isinstance(node, ProcessItem) and "table" in nd:
                node.table = sets_from_list(nd["table"], by_id,
                                            node.input_docs(), node.output_docs())
        missing = 0
        for nd in data["nodes"]:                 # attachments of the documents
            node = by_id[nd["id"]]
            entries = nd.get("attachments")
            if not isinstance(node, DocumentItem) or not isinstance(entries, list):
                continue
            for e in entries:
                member = e.get("file") if isinstance(e, dict) else None
                src = files.get(member) if isinstance(member, str) else None
                if src is None:
                    missing += 1
                    continue
                name = unique_name(safe_filename(e.get("name") or posixpath.basename(member)),
                                   [a.name for a in node.attachments])
                node.attachments.append(Attachment(name, src))
            node.attachments_changed()
        for nd in data["nodes"]:                 # web links of the documents
            node = by_id[nd["id"]]
            entries = nd.get("links")
            if not isinstance(node, DocumentItem) or not isinstance(entries, list):
                continue
            for e in entries:
                url = e.get("url") if isinstance(e, dict) else None
                if not isinstance(url, str) or not url.strip():
                    continue
                desc = e.get("description")
                node.links.append(Link(_one_line(desc)[:MAX_LINK_DESC]
                                       if isinstance(desc, str) else "", url.strip()))
            node.attachments_changed()
        roles = RoleDictionary.from_list(data.get("roles"))
        # Everything parsed fine - now replace the current diagram.
        self.reset()
        self.roles = roles
        self.rolesChanged.emit()
        for n in by_id.values():
            self.addItem(n)
        for c in conns:
            self.addItem(c)
        for n in by_id.values():
            n.ensure_ports_fit(self.snap)
            n.refresh_geometry()
        self.relayout()
        return missing

    def reset(self) -> None:
        self.cancel_pending()
        for n in self.nodes():                   # their attached files are not needed any more
            self.discard_attachments(n)
        self.clear()
        self.roles = RoleDictionary()
        self.rolesChanged.emit()
        self.set_dirty(False)

    # ---- export ------------------------------------------------------------ #
    def _export_rect(self) -> QRectF | None:
        self.cancel_pending()
        self.clearSelection()
        if not self.nodes():
            return None
        return self.itemsBoundingRect().adjusted(-30, -30, 30, 30)

    def export_png(self, path: str, scale: float = 2.0) -> bool:
        rect = self._export_rect()
        if rect is None:
            return False
        self.exporting = True
        try:
            img = QImage(int(rect.width() * scale), int(rect.height() * scale),
                         QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.white)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self.render(p, QRectF(img.rect()), rect)
            p.end()
            return img.save(path)
        finally:
            self.exporting = False

    def export_svg(self, path: str) -> bool:
        rect = self._export_rect()
        if rect is None or QSvgGenerator is None:
            return False
        self.exporting = True
        try:
            gen = QSvgGenerator()
            gen.setFileName(path)
            gen.setSize(QSize(int(rect.width()), int(rect.height())))
            gen.setViewBox(QRectF(0, 0, rect.width(), rect.height()))
            gen.setTitle(APP_NAME)
            p = QPainter(gen)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.render(p, QRectF(0, 0, rect.width(), rect.height()), rect)
            p.end()
            return True
        finally:
            self.exporting = False


# --------------------------------------------------------------------------- #
# View: zoom + pan
# --------------------------------------------------------------------------- #
class DiagramView(QGraphicsView):
    def __init__(self, scene: DiagramScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.TextAntialiasing)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._pan_last = None
        self.centerOn(0, 0)

    def zoom(self, factor: float) -> None:
        cur = self.transform().m11()
        new = max(0.2, min(4.0, cur * factor))
        f = new / cur
        self.scale(f, f)

    def reset_zoom(self) -> None:
        self.resetTransform()

    def zoom_to_fit(self) -> None:
        sc = self.scene()
        if sc.nodes():
            rect = sc.itemsBoundingRect().adjusted(-40, -40, 40, 40)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            if self.transform().m11() > 1.5:
                self.resetTransform()
                self.centerOn(rect.center())

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.15 ** (event.angleDelta().y() / 120.0))
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event.position().toPoint()
            self.viewport().setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pan_last is not None:
            cur = event.position().toPoint()
            d = cur - self._pan_last
            self._pan_last = cur
            hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
            hb.setValue(hb.value() - d.x())
            vb.setValue(vb.value() - d.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_last is not None:
            self._pan_last = None
            if self.scene().mode == MODE_SELECT:
                self.viewport().unsetCursor()
            else:
                self.viewport().setCursor(QCursor(Qt.CursorShape.CrossCursor))
            event.accept()
            return
        super().mouseReleaseEvent(event)


# --------------------------------------------------------------------------- #
# Process table panel (under the diagram, shown while ONE process is selected)
# --------------------------------------------------------------------------- #
BAND_COLORS = (QColor("#ffffff"), QColor("#eaf1fb"))      # alternate between sets
TABLE_COLUMNS = ("Input document", "Role", "Term", "Process", "Output document")
COL_IN, COL_ROLE, COL_TERM, COL_PROC, COL_OUT = range(5)
TEXT_FIELDS = {COL_ROLE: "role", COL_TERM: "term", COL_PROC: "process"}
DEFAULT_PANEL_HEIGHT = 240
C_STALE = QColor("#b3261e")           # a role that is not in the dictionary


class ProcessTable(QTableWidget):
    """A QTableWidget that keeps Delete, Backspace, F2 and Ctrl+A for itself -
    otherwise the window's shortcuts would delete/rename the selected diagram
    item while the user is working in the table."""

    clearRequested = Signal()

    def editing(self) -> bool:
        return self.state() == QAbstractItemView.State.EditingState

    def event(self, e):
        if e.type() == QEvent.Type.ShortcutOverride:
            key = e.key()
            ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if (key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace, Qt.Key.Key_F2)
                    or (ctrl and key == Qt.Key.Key_A)):
                e.accept()
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        if (e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
                and not self.editing()):
            self.clearRequested.emit()          # empties the current cell
            e.accept()
            return
        super().keyPressEvent(e)


class DocDelegate(QStyledItemDelegate):
    """Drop-down editor for the Input / Output document cells. It lists the
    documents currently linked to the process (plus an empty entry)."""

    def __init__(self, panel: "ProcessTablePanel", kind: str, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.kind = kind                  # "in" or "out"
        self._cands: list = []

    def createEditor(self, parent, option, index):
        self._cands = self.panel.candidates(self.kind)
        combo = QComboBox(parent)
        combo.addItem("")                 # no document
        for label in unique_labels(self._cands):
            combo.addItem(label)
        combo.activated.connect(lambda *_: self._finish(combo))
        QTimer.singleShot(0, lambda: self._popup(combo))      # open the list at once
        return combo

    def _finish(self, combo) -> None:
        self.commitData.emit(combo)
        self.closeEditor.emit(combo, QAbstractItemDelegate.EndEditHint.NoHint)

    @staticmethod
    def _popup(combo) -> None:
        try:
            combo.showPopup()
        except RuntimeError:              # editor already closed
            pass

    def setEditorData(self, editor, index) -> None:
        doc = self.panel.doc_at(index.row(), self.kind)
        pos = next((k for k, c in enumerate(self._cands) if c is doc), -1)
        editor.setCurrentIndex(pos + 1 if (doc is not None and pos >= 0) else 0)

    def setModelData(self, editor, model, index) -> None:
        k = editor.currentIndex()
        node = self._cands[k - 1] if 0 < k <= len(self._cands) else None
        self.panel.set_doc(index.row(), self.kind, node)


class RoleDelegate(DocDelegate):
    """Drop-down editor for the Role cell of a set: the roles of the
    dictionary (plus an empty entry). The cell spans all rows of the set, so
    there is exactly one list per set."""

    def __init__(self, panel: "ProcessTablePanel", parent=None):
        super().__init__(panel, "role", parent)
        self._names: list[str] = []

    def createEditor(self, parent, option, index):
        self._names = self.panel.role_choices(index.row())
        combo = QComboBox(parent)
        combo.addItem("")                 # no role
        for name in self._names:
            combo.addItem(name if self.panel.scene.roles.has(name)
                          else f"{name}  (not in the dictionary)")
        combo.activated.connect(lambda *_: self._finish(combo))
        QTimer.singleShot(0, lambda: self._popup(combo))
        return combo

    def setEditorData(self, editor, index) -> None:
        cur = self.panel.role_at(index.row())
        editor.setCurrentIndex(self._names.index(cur) + 1 if cur in self._names else 0)

    def setModelData(self, editor, model, index) -> None:
        k = editor.currentIndex()
        self.panel.set_role(index.row(), self._names[k - 1] if 0 < k <= len(self._names) else "")


class ProcessTablePanel(QWidget):
    """Table of the selected process: Input document | Role | Term | Process |
    Output document. A set (Role/Term/Process) spans as many rows as it has
    document rows, so several inputs/outputs can share one set."""

    rolesRequested = Signal()             # "Roles..." button: open the dictionary window

    def __init__(self, scene: DiagramScene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.process: ProcessItem | None = None
        self._row_map: list[tuple[int, int]] = []      # table row -> (set, row in set)
        self._building = False
        self._timer = QTimer(self)                     # deferred refresh
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.refresh)

        self.title = QLabel()
        self.title.setStyleSheet("font-weight: bold;")
        self.hint = QLabel()
        self.hint.setStyleSheet("color: #6b7380;")
        self.b_set = self._button(
            "Add set", "Start a new Role / Term / Process set", self.add_set)
        self.b_row = self._button(
            "Add row", "Give the selected set another row, to link one more "
            "input / output document to the same Role / Term / Process", self.add_row)
        self.b_del_row = self._button(
            "Delete row", "Remove the selected row from its set", self.delete_row)
        self.b_del_set = self._button(
            "Delete set", "Remove the selected set with all its rows", self.delete_set)
        self.b_roles = self._button(
            "Roles\u2026", "Open the Roles dictionary window", self.rolesRequested.emit)

        t = self.table = ProcessTable(0, len(TABLE_COLUMNS), self)
        t.setHorizontalHeaderLabels(list(TABLE_COLUMNS))
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(28)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._delegates = [DocDelegate(self, "in", t), DocDelegate(self, "out", t)]
        t.setItemDelegateForColumn(COL_IN, self._delegates[0])
        t.setItemDelegateForColumn(COL_OUT, self._delegates[1])
        self._role_delegate = RoleDelegate(self, t)
        t.setItemDelegateForColumn(COL_ROLE, self._role_delegate)
        t.itemChanged.connect(self._on_item_changed)
        t.currentCellChanged.connect(lambda *_: self._update_buttons())
        t.clearRequested.connect(self.clear_current_cell)

        top = QHBoxLayout()
        top.addWidget(self.title, 1)
        for b in (self.b_set, self.b_row, self.b_del_row, self.b_del_set, self.b_roles):
            top.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addLayout(top)
        lay.addWidget(t, 1)
        lay.addWidget(self.hint)
        self.setMinimumHeight(140)
        self._update_buttons()

    # ---- helpers ------------------------------------------------------------ #
    def _button(self, text: str, tip: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        # no keyboard focus: Delete/Backspace must never reach the window shortcuts
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(lambda _=False: slot())
        return b

    @staticmethod
    def _cell(text: str, brush: QBrush) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setBackground(brush)
        item.setForeground(QBrush(C_TEXT))
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return item

    @staticmethod
    def _doc_text(doc, labels: dict) -> str:
        return "" if doc is None else labels.get(id(doc), plain_name(doc))

    def candidates(self, kind: str) -> list:
        """Documents offered in the drop-down of the Input / Output column."""
        if self.process is None:
            return []
        return self.process.input_docs() if kind == "in" else self.process.output_docs()

    def role_at(self, row: int) -> str:
        if self.process is None or not 0 <= row < len(self._row_map):
            return ""
        return self.process.table[self._row_map[row][0]].role

    def role_choices(self, row: int) -> list[str]:
        """Roles offered in the drop-down: the dictionary, plus the role the set
        has now if it is no longer (or never was) in the dictionary."""
        names = self.scene.roles.names()
        cur = self.role_at(row)
        if cur and cur not in names:
            names.append(cur)
        return names

    def doc_at(self, row: int, kind: str):
        if self.process is None or not 0 <= row < len(self._row_map):
            return None
        si, rj = self._row_map[row]
        r = self.process.table[si].rows[rj]
        return r.inp if kind == "in" else r.out

    def _current(self):
        """(set index, row index within the set) of the current row, or (None, None)."""
        row = self.table.currentRow()
        if 0 <= row < len(self._row_map):
            return self._row_map[row]
        return None, None

    def _update_buttons(self) -> None:
        p = self.process
        si, _rj = self._current()
        self.b_set.setEnabled(p is not None)
        self.b_row.setEnabled(p is not None and bool(p.table))
        self.b_del_set.setEnabled(si is not None)
        self.b_del_row.setEnabled(si is not None and len(p.table[si].rows) > 1)

    # ---- showing a process ----------------------------------------------------- #
    def set_process(self, process) -> None:
        changed = process is not self.process
        self.process = process
        if process is None:
            self._building = True
            try:
                self.table.clearSpans()
                self.table.clearContents()
                self.table.setRowCount(0)
            finally:
                self._building = False
            self._row_map = []
            self._update_buttons()
            return
        self.refresh(keep=not changed)

    def on_content_changed(self) -> None:
        """The diagram changed (rename, connection added/removed, ...)."""
        if self.process is None or not self.isVisible() or self.table.editing():
            return
        self._timer.start()

    def refresh(self, select=None, keep: bool = True) -> None:
        """Rebuild the table from the process. `select` = (set, row, column) of
        the cell to make current afterwards."""
        p = self.process
        if p is None:
            return
        try:
            gone = p.scene() is None
        except RuntimeError:              # the C++ item is already deleted
            gone = True
        if gone:
            self.set_process(None)
            return
        t = self.table
        prev = (t.currentRow(), t.currentColumn()) if keep else (-1, -1)
        ins, outs = p.input_docs(), p.output_docs()
        lab_in = dict(zip(map(id, ins), unique_labels(ins)))
        lab_out = dict(zip(map(id, outs), unique_labels(outs)))
        self._building = True
        try:
            t.clearSpans()
            t.clearContents()
            t.setRowCount(sum(len(st.rows) for st in p.table))
            self._row_map = []
            r0 = 0
            for si, st in enumerate(p.table):
                brush = QBrush(BAND_COLORS[si % 2])
                n = len(st.rows)
                for rj, row in enumerate(st.rows):
                    self._row_map.append((si, rj))
                    t.setItem(r0 + rj, COL_IN,
                              self._cell(self._doc_text(row.inp, lab_in), brush))
                    t.setItem(r0 + rj, COL_OUT,
                              self._cell(self._doc_text(row.out, lab_out), brush))
                for col, field in TEXT_FIELDS.items():
                    cell = self._cell(getattr(st, field), brush)
                    if col == COL_ROLE and st.role and not self.scene.roles.has(st.role):
                        cell.setForeground(QBrush(C_STALE))
                        cell.setToolTip("This role is not in the Roles dictionary.")
                    t.setItem(r0, col, cell)
                    if n > 1:
                        t.setSpan(r0, col, n, 1)      # Role/Term/Process cover all rows
                r0 += n
        finally:
            self._building = False
        if select is not None:
            si, rj, col = select
            if (si, rj) in self._row_map:
                t.setCurrentCell(self._row_map.index((si, rj)), col)
        elif 0 <= prev[0] < t.rowCount() and prev[1] >= 0:
            t.setCurrentCell(prev[0], prev[1])
        n_sets = len(p.table)
        self.title.setText(f"Process: {plain_name(p)}   "
                           f"({n_sets} set{'' if n_sets == 1 else 's'})")
        if not ins and not outs:
            self.hint.setText("No documents are linked to this process yet - connect "
                              "documents to it on the diagram, then pick them here.")
        else:
            self.hint.setText("Double-click a cell to edit it. Add row gives the "
                              "selected set another row for one more document; "
                              "Delete empties the current cell. Roles come from "
                              "the Roles dictionary (Roles\u2026 button).")
        self._update_buttons()

    # ---- editing -------------------------------------------------------------------- #
    def _changed(self, select=None) -> None:
        self.scene.set_dirty(True)
        self.refresh(select)

    def _on_item_changed(self, item) -> None:
        if self._building or self.process is None:
            return
        col, row = item.column(), item.row()
        if col not in TEXT_FIELDS or not 0 <= row < len(self._row_map):
            return
        si, _rj = self._row_map[row]
        st = self.process.table[si]
        field = TEXT_FIELDS[col]
        if getattr(st, field) != item.text():
            setattr(st, field, item.text())
            self.scene.set_dirty(True)

    def set_role(self, row: int, name: str) -> None:
        """Called by the Role drop-down delegate."""
        if self.process is None or not 0 <= row < len(self._row_map):
            return
        st = self.process.table[self._row_map[row][0]]
        if st.role == name:
            return
        st.role = name
        self.scene.set_dirty(True)
        self._timer.start()

    def set_doc(self, row: int, kind: str, node) -> None:
        """Called by the drop-down delegate when a document was picked."""
        if self.process is None or not 0 <= row < len(self._row_map):
            return
        si, rj = self._row_map[row]
        r = self.process.table[si].rows[rj]
        if (r.inp if kind == "in" else r.out) is node:
            return
        if kind == "in":
            r.inp = node
        else:
            r.out = node
        self.scene.set_dirty(True)
        self._timer.start()               # rebuild once the delegate is done

    def clear_current_cell(self) -> None:
        p = self.process
        row, col = self.table.currentRow(), self.table.currentColumn()
        if p is None or not 0 <= row < len(self._row_map):
            return
        si, rj = self._row_map[row]
        st = p.table[si]
        if col == COL_IN:
            st.rows[rj].inp = None
        elif col == COL_OUT:
            st.rows[rj].out = None
        elif col in TEXT_FIELDS:
            setattr(st, TEXT_FIELDS[col], "")
        else:
            return
        self._changed((si, rj, col))

    def add_set(self) -> None:
        p = self.process
        if p is None:
            return
        self.table.setFocus()             # commits a cell that is being edited
        p.table.append(TableSet())
        self._changed((len(p.table) - 1, 0, COL_ROLE))

    def add_row(self) -> None:
        p = self.process
        if p is None or not p.table:
            return
        self.table.setFocus()
        si, rj = self._current()
        if si is None:                    # nothing selected: extend the last set
            si, rj = len(p.table) - 1, len(p.table[-1].rows) - 1
        elif self.table.currentColumn() in TEXT_FIELDS:
            rj = len(p.table[si].rows) - 1     # on the spanning cells: append at the end
        p.table[si].rows.insert(rj + 1, TableRow())
        self._changed((si, rj + 1, COL_IN))

    def delete_row(self) -> None:
        p = self.process
        si, rj = self._current()
        if p is None or si is None or len(p.table[si].rows) < 2:
            return
        self.table.setFocus()
        del p.table[si].rows[rj]
        self._changed((si, min(rj, len(p.table[si].rows) - 1), COL_IN))

    def delete_set(self) -> None:
        p = self.process
        si, _rj = self._current()
        if p is None or si is None:
            return
        self.table.setFocus()
        del p.table[si]
        self._changed((min(si, len(p.table) - 1), 0, COL_ROLE) if p.table else None)


# --------------------------------------------------------------------------- #
# Roles dictionary window
# --------------------------------------------------------------------------- #
ROLE_COLUMNS = ("Role", "Description", "Actual set")
RCOL_NAME, RCOL_DESC, RCOL_SET = range(3)


class MembersDialog(QDialog):
    """Edit the actual set of one role: tick the roles it includes and the
    users that belong to it. Every user already known to the dictionary is
    offered, because one person can hold several roles; new names are typed
    below the list. Roles that would make a loop cannot be ticked."""

    def __init__(self, roles: RoleDictionary, role: Role, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Actual set of “{role.name}”")
        self.setModal(True)
        self.resize(560, 360)
        self.role_name = role.name
        self._role_items: list = []                  # (role name, list item)

        intro = QLabel("The actual set is what the role consists of right now: "
                       "other roles of the dictionary and/or users. A user may belong "
                       "to several roles.")
        intro.setWordWrap(True)

        self.role_list = QListWidget()
        for other in roles:
            if other.name == role.name:
                continue
            item = QListWidgetItem(other.name)
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            if not roles.can_include(role.name, other.name):
                flags &= ~Qt.ItemFlag.ItemIsEnabled
                item.setToolTip(f"“{other.name}” already includes "
                                f"“{role.name}” - this would make a loop.")
            item.setFlags(flags)
            item.setCheckState(Qt.CheckState.Checked if other.name in role.roles
                               else Qt.CheckState.Unchecked)
            self.role_list.addItem(item)
            self._role_items.append((other.name, item))
        left = QVBoxLayout()
        left.addWidget(QLabel("Included roles (tick):"))
        left.addWidget(self.role_list, 1)
        if not self._role_items:
            left.addWidget(QLabel("There are no other roles in the dictionary yet."))

        # Every user already in the dictionary is offered: one person can belong
        # to several roles. Ticked = a member of this role.
        self._roles = roles
        self.user_list = QListWidget()
        for u in roles.all_users():
            self._add_user_item(u, u in role.users)
        for u in role.users:                          # this role's own users are always ticked
            item = self._find_user(u)
            if item is None:
                self._add_user_item(u, True)
            else:
                item.setText(u)                       # (same user spelled differently elsewhere)
                item.setCheckState(Qt.CheckState.Checked)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("New user name, Enter to add (several: separate with commas)")
        self.b_add = QPushButton("Add")
        self.b_add.clicked.connect(lambda _=False: self.add_typed())
        self.user_edit.returnPressed.connect(self._on_return)
        row = QHBoxLayout()
        row.addWidget(self.user_edit, 1)
        row.addWidget(self.b_add)
        right = QVBoxLayout()
        right.addWidget(QLabel("Users (tick the ones that belong to this role):"))
        right.addWidget(self.user_list, 1)
        right.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        for b in buttons.buttons():
            b.setAutoDefault(False)          # Enter in the name field means "Add"
        self.b_add.setDefault(True)

        cols = QHBoxLayout()
        cols.addLayout(left, 1)
        cols.addLayout(right, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addLayout(cols, 1)
        lay.addWidget(buttons)

    # ---- users ------------------------------------------------------------- #
    def _add_user_item(self, name: str, checked: bool):
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        others = [n for n in self._roles.roles_of_user(name) if n != self.role_name]
        if others:
            item.setToolTip("Also in: " + ", ".join(others))
        self.user_list.addItem(item)
        return item

    def _find_user(self, name: str):
        """The list entry for `name` (ignoring case), or None."""
        key = name.casefold()
        for i in range(self.user_list.count()):
            item = self.user_list.item(i)
            if item.text().casefold() == key:
                return item
        return None

    def add_users(self, text: str) -> int:
        """Tick the named users, adding the ones that are new. Returns how many
        entries were created."""
        created = 0
        for name in parse_usernames(text):
            item = self._find_user(name)
            if item is None:
                self._add_user_item(name, True)
                created += 1
            else:
                item.setCheckState(Qt.CheckState.Checked)
        return created

    def add_typed(self) -> None:
        self.add_users(self.user_edit.text())
        self.user_edit.clear()
        self.user_edit.setFocus()

    def _on_return(self) -> None:
        if self.user_edit.text().strip():
            self.add_typed()
        else:
            self.accept()                    # Enter on an empty field = OK

    # ---- result -------------------------------------------------------------- #
    def accept(self) -> None:
        self.add_users(self.user_edit.text())    # a name typed but not added yet
        super().accept()

    def members(self):
        """(users, included role names) as edited."""
        roles = [n for n, it in self._role_items
                 if it.checkState() == Qt.CheckState.Checked]
        users = [self.user_list.item(i).text() for i in range(self.user_list.count())
                 if self.user_list.item(i).checkState() == Qt.CheckState.Checked]
        return users, roles


class RolesTable(QTableWidget):
    editRequested = Signal()

    def editing(self) -> bool:
        return self.state() == QAbstractItemView.State.EditingState

    def keyPressEvent(self, e):
        if (e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.editing()
                and self.currentColumn() == RCOL_SET):
            self.editRequested.emit()
            e.accept()
            return
        super().keyPressEvent(e)


class RolesWindow(QWidget):
    """Separate window with the roles dictionary: Role | Description | Actual set."""

    def __init__(self, scene: DiagramScene, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.scene = scene
        self._building = False
        self._names: list[str] = []                   # table row -> role name
        self.setWindowTitle("Roles dictionary")
        self.resize(780, 420)
        self._timer = QTimer(self)                    # deferred refresh
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

        self.b_add = self._button("Add role", "Add a new role to the dictionary", self.add_role)
        self.b_del = self._button("Delete role", "Delete the selected role", self.delete_role)
        self.b_members = self._button(
            "Edit actual set…", "Choose the roles and users the selected role consists of",
            self.edit_members)
        self.status = QLabel()
        self.status.setWordWrap(True)

        t = self.table = RolesTable(0, len(ROLE_COLUMNS), self)
        t.setHorizontalHeaderLabels(list(ROLE_COLUMNS))
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setStretchLastSection(True)
        t.setColumnWidth(RCOL_NAME, 170)
        t.setColumnWidth(RCOL_DESC, 280)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.itemChanged.connect(self._on_item_changed)
        t.currentCellChanged.connect(lambda *_: self._update_buttons())
        t.cellDoubleClicked.connect(self._on_double_click)
        t.editRequested.connect(self.edit_members)

        top = QHBoxLayout()
        top.addWidget(self.b_add)
        top.addWidget(self.b_del)
        top.addWidget(self.b_members)
        top.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(t, 1)
        lay.addWidget(self.status)
        self._say("Role and Description are edited in place. In the Actual set column, "
                  "double-click (or press Enter) to choose included roles and users.")
        scene.rolesChanged.connect(self.schedule_refresh)
        self.refresh()

    # ---- helpers ---------------------------------------------------------------- #
    def _button(self, text: str, tip: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(lambda _=False: slot())
        return b

    def _say(self, text: str, error: bool = False) -> None:
        self.status.setStyleSheet("color: #b3261e;" if error else "color: #6b7380;")
        self.status.setText(text)

    def _current_name(self):
        row = self.table.currentRow()
        return self._names[row] if 0 <= row < len(self._names) else None

    def _update_buttons(self) -> None:
        has = self._current_name() is not None
        self.b_del.setEnabled(has)
        self.b_members.setEnabled(has)

    def schedule_refresh(self) -> None:
        self._timer.start(0)

    def _flush(self) -> None:
        if self.table.editing():             # never pull the editor away from under the user
            self._timer.start(100)
            return
        self.refresh()

    # ---- showing the dictionary -------------------------------------------------- #
    def refresh(self, select: "str | None" = None) -> None:
        roles = self.scene.roles
        t = self.table
        if select is None:
            select = self._current_name()
        self._building = True
        try:
            t.clearContents()
            t.setRowCount(len(roles))
            self._names = roles.names()
            for i, r in enumerate(roles):
                t.setItem(i, RCOL_NAME, QTableWidgetItem(r.name))
                t.setItem(i, RCOL_DESC, QTableWidgetItem(r.description))
                cell = QTableWidgetItem(roles.members_text(r.name))
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                everyone = roles.effective_users(r.name)
                cell.setToolTip("All users: " + (", ".join(everyone) if everyone else "(none)")
                                + "\n[Name] = an included role. Double-click to edit.")
                t.setItem(i, RCOL_SET, cell)
        finally:
            self._building = False
        if select in self._names:
            t.setCurrentCell(self._names.index(select), RCOL_NAME)
        self._update_buttons()

    # ---- editing --------------------------------------------------------------------- #
    def _on_item_changed(self, item) -> None:
        if self._building:
            return
        row, col = item.row(), item.column()
        if not 0 <= row < len(self._names):
            return
        name = self._names[row]
        if col == RCOL_NAME:
            if item.text() == name:
                return
            try:
                new = self.scene.rename_role(name, item.text())
            except ValueError as exc:
                self._say(str(exc), error=True)
                self.schedule_refresh()           # puts the old name back
                return
            self._say(f"Renamed to “{new}”.")
        elif col == RCOL_DESC:
            self.scene.set_role_description(name, item.text())

    def _on_double_click(self, row: int, col: int) -> None:
        if col == RCOL_SET:
            self.edit_members()

    def add_role(self) -> None:
        self.table.setFocus()                     # commits a cell being edited
        role = self.scene.add_role()
        self.refresh(select=role.name)
        item = self.table.item(self._names.index(role.name), RCOL_NAME)
        self.table.editItem(item)                 # type the name at once
        self._say("Type the name of the new role.")

    def delete_role(self) -> None:
        name = self._current_name()
        if name is None:
            return
        used = self.scene.role_usage(name)
        parents = [r.name for r in self.scene.roles if name in r.roles]
        lines = [f"Delete the role “{name}”?"]
        if used:
            lines.append(f"It is chosen in {used} set(s) of process tables; "
                         "the Role cell of those sets will be emptied.")
        if parents:
            lines.append("It will be removed from the actual set of: " + ", ".join(parents) + ".")
        answer = QMessageBox.question(
            self, "Delete role", "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.scene.delete_role(name)
        self._say(f"Deleted “{name}”.")

    def edit_members(self) -> None:
        name = self._current_name()
        role = self.scene.roles.find(name) if name is not None else None
        if role is None:
            return
        dlg = MembersDialog(self.scene.roles, role, self)
        if not dlg.exec():                        # 1 = accepted
            return
        users, included = dlg.members()
        try:
            self.scene.set_role_members(name, users, included)
        except ValueError as exc:
            self._say(str(exc), error=True)
            return
        self._say(f"Updated the actual set of “{name}”.")


# --------------------------------------------------------------------------- #
# Files panel (under the diagram, shown while ONE document is selected)
# --------------------------------------------------------------------------- #
class FileList(QListWidget):
    """List of attached files. Like the process table it keeps Delete,
    Backspace and Ctrl+A for itself instead of passing them to the window
    (where Delete would remove the selected document from the diagram)."""

    removeRequested = Signal()

    def event(self, e):
        if e.type() == QEvent.Type.ShortcutOverride:
            key = e.key()
            ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if (key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
                    or (ctrl and key == Qt.Key.Key_A)):
                e.accept()
                return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.removeRequested.emit()
            e.accept()
            return
        super().keyPressEvent(e)


class LinkDialog(QDialog):
    """The small window for a link: a Description and the URL itself. OK stays
    disabled until the URL is acceptable; the problem is shown under the fields."""

    def __init__(self, description: str = "", url: str = "", editing: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit link" if editing else "Add link")
        self.setModal(True)
        self.resize(520, 160)
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("What the link is about (optional)")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/page")
        self.desc_edit.setText(description)
        self.url_edit.setText(url)
        self.problem = QLabel()
        self.problem.setStyleSheet("color: #b3261e;")
        self.problem.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Description:", self.desc_edit)
        form.addRow("URL:", self.url_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.problem)
        lay.addStretch(1)
        lay.addWidget(buttons)
        self.url_edit.textChanged.connect(lambda *_: self._check())
        self._check()
        self.desc_edit.setFocus()

    def _check(self) -> bool:
        text = self.url_edit.text()
        try:
            normalize_url(text)
        except ValueError as exc:
            self.ok_button.setEnabled(False)
            self.problem.setText(str(exc) if text.strip() else "")
            return False
        self.ok_button.setEnabled(True)
        self.problem.setText("")
        return True

    def accept(self) -> None:
        if self._check():                    # (Enter must not get past a bad address)
            super().accept()

    def result_link(self):
        """(description, url) as typed, tidied: one-line description and the
        address with https:// added when it had no scheme."""
        return (_one_line(self.desc_edit.text())[:MAX_LINK_DESC],
                normalize_url(self.url_edit.text()))


class DocumentFilesPanel(QWidget):
    """Files and web links attached to the selected document."""

    def __init__(self, scene: DiagramScene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.document: DocumentItem | None = None
        self._entries: list[tuple[str, int]] = []      # list row -> ("file" | "link", index)

        self.title = QLabel()
        self.title.setStyleSheet("font-weight: bold;")
        self.hint = QLabel("Add files attaches copies of files, Add link a web address "
                           "(double-click a link to open it). Everything is stored inside "
                           "the .bpmn file when the diagram is saved.")
        self.hint.setStyleSheet("color: #6b7380;")
        self.b_add = self._button(
            "Add files...", "Attach files to the document", self.add_files)
        self.b_link = self._button(
            "Add link...", "Attach a web address (URL) to the document", self.add_link)
        self.b_edit = self._button(
            "Edit link...", "Change the description or the URL of the selected link",
            self.edit_link)
        self.b_open = self._button(
            "Open link", "Open the selected link in the web browser", self.open_link)
        self.b_remove = self._button(
            "Remove", "Detach the selected files and links from the document "
            "(the original files are not touched)", self.remove_selected)
        self.b_save = self._button(
            "Save copy...", "Write the selected attached file to disk", self.save_copy)

        lst = self.list = FileList(self)
        lst.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lst.itemSelectionChanged.connect(self._update_buttons)
        lst.itemDoubleClicked.connect(self._on_double_click)
        lst.removeRequested.connect(self.remove_selected)

        top = QHBoxLayout()
        top.addWidget(self.title, 1)
        for b in (self.b_add, self.b_link, self.b_edit, self.b_open, self.b_remove, self.b_save):
            top.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        lay.addLayout(top)
        lay.addWidget(lst, 1)
        lay.addWidget(self.hint)
        self.setMinimumHeight(140)
        self._update_buttons()

    def _button(self, text: str, tip: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        # no keyboard focus: Delete/Backspace must never reach the window shortcuts
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(lambda _=False: slot())
        return b

    def _selected_rows(self) -> list[int]:
        return sorted({self.list.row(it) for it in self.list.selectedItems()})

    def _selected_entries(self) -> list[tuple[str, int]]:
        return [self._entries[r] for r in self._selected_rows() if r < len(self._entries)]

    def _update_buttons(self) -> None:
        sel = self._selected_entries()
        one = sel[0][0] if len(sel) == 1 else None
        has = self.document is not None
        self.b_add.setEnabled(has)
        self.b_link.setEnabled(has)
        self.b_remove.setEnabled(bool(sel))
        self.b_save.setEnabled(one == "file")
        self.b_edit.setEnabled(one == "link")
        self.b_open.setEnabled(one == "link")

    # ---- showing a document ---------------------------------------------------- #
    def set_document(self, doc) -> None:
        self.document = doc
        if doc is None:
            self._entries = []
            self.list.clear()
            self._update_buttons()
            return
        self.refresh()

    def on_content_changed(self) -> None:
        """The diagram changed (e.g. the document was renamed)."""
        if self.document is not None and self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        doc = self.document
        if doc is None:
            return
        try:
            gone = doc.scene() is None
        except RuntimeError:              # the C++ item is already deleted
            gone = True
        if gone:
            self.set_document(None)
            return
        keep = self._selected_rows()
        self._entries = []
        self.list.clear()
        for i, a in enumerate(doc.attachments):
            self.list.addItem(QListWidgetItem(f"{a.name}    ({format_size(a.size())})"))
            self._entries.append(("file", i))
        for i, link in enumerate(doc.links):
            item = QListWidgetItem(link_text(link))
            item.setToolTip(link.url)
            self.list.addItem(item)
            self._entries.append(("link", i))
        for r in keep:
            if r < self.list.count():
                self.list.item(r).setSelected(True)
        n, m = len(doc.attachments), len(doc.links)
        counts = f"{n} file{'' if n == 1 else 's'}"
        if m:
            counts += f", {m} link{'' if m == 1 else 's'}"
        self.title.setText(f"Document: {plain_name(doc)}   ({counts})")
        self._update_buttons()

    def _select_entry(self, kind: str, index: int) -> None:
        for it in self.list.selectedItems():
            it.setSelected(False)
        if (kind, index) in self._entries:
            self.list.item(self._entries.index((kind, index))).setSelected(True)
        self._update_buttons()

    # ---- actions ------------------------------------------------------------------- #
    def add_files(self) -> None:
        doc = self.document
        if doc is None:
            return
        paths, _filter = QFileDialog.getOpenFileNames(
            self, "Attach files to the document", "")
        if not paths:
            return
        failed = []
        for p in paths:
            try:
                doc.attach(p, self.scene.store)
            except OSError as exc:
                failed.append(f"{Path(p).name}: {exc.strerror or exc}")
        if len(failed) < len(paths):
            self.scene.touch()
        self.refresh()
        if failed:
            QMessageBox.warning(self, APP_NAME, "Some files could not be attached:\n"
                                + "\n".join(failed))

    def add_link(self) -> None:
        doc = self.document
        if doc is None:
            return
        dlg = LinkDialog(parent=self)
        if not dlg.exec():                    # 1 = accepted
            return
        description, url = dlg.result_link()
        doc.add_link(description, url)
        self.scene.touch()
        self.refresh()
        self._select_entry("link", len(doc.links) - 1)

    def _the_link(self):
        """(index, Link) of the one selected link, else None."""
        sel = self._selected_entries()
        if self.document is None or len(sel) != 1 or sel[0][0] != "link":
            return None
        return sel[0][1], self.document.links[sel[0][1]]

    def edit_link(self) -> None:
        got = self._the_link()
        if got is None:
            return
        index, link = got
        dlg = LinkDialog(link.description, link.url, editing=True, parent=self)
        if not dlg.exec():
            return
        description, url = dlg.result_link()
        if (description, url) != (link.description, link.url):
            self.document.set_link(index, description, url)
            self.scene.touch()
            self.refresh()

    def open_link(self) -> None:
        got = self._the_link()
        if got is not None:
            self._open(got[1])

    def _open(self, link: Link) -> None:
        try:
            url = normalize_url(link.url)     # also keeps file:, javascript: ... from being opened
        except ValueError as exc:
            QMessageBox.warning(self, APP_NAME, f"This link is not opened:\n{link.url}\n\n{exc}")
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, APP_NAME, f"Could not open the link:\n{url}")

    def _on_double_click(self, item) -> None:
        row = self.list.row(item)
        if self.document is not None and 0 <= row < len(self._entries):
            kind, index = self._entries[row]
            if kind == "link":
                self._open(self.document.links[index])

    def remove_selected(self) -> None:
        doc = self.document
        sel = self._selected_entries()
        if doc is None or not sel:
            return
        for index in sorted((i for k, i in sel if k == "file"), reverse=True):
            doc.detach(index, self.scene.store)   # from the end, so indexes stay valid
        for index in sorted((i for k, i in sel if k == "link"), reverse=True):
            doc.remove_link(index)
        self.scene.touch()
        self.refresh()

    def save_copy(self) -> None:
        doc = self.document
        sel = self._selected_entries()
        if doc is None or len(sel) != 1 or sel[0][0] != "file":
            return
        att = doc.attachments[sel[0][1]]
        dest, _filter = QFileDialog.getSaveFileName(
            self, "Save a copy of the attached file", att.name)
        if not dest:
            return
        try:
            shutil.copyfile(att.path, dest)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not save the file:\n{exc}")
            return
        self.scene.message.emit(f"Saved a copy of {att.name} to {dest}", False)


# --------------------------------------------------------------------------- #
# Toolbar icons (drawn in code, so no resource files are needed)
# --------------------------------------------------------------------------- #
def make_icon(kind: str) -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(C_OUTLINE, 2)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    if kind == MODE_SELECT:
        p.setBrush(Qt.GlobalColor.white)
        p.drawPolygon(QPolygonF([QPointF(9, 5), QPointF(9, 25), QPointF(14, 20),
                                 QPointF(18, 28), QPointF(21, 26.5),
                                 QPointF(17, 19), QPointF(24, 19)]))
    elif kind == MODE_PROCESS:
        p.setBrush(C_PROCESS_FILL)
        p.drawRect(QRectF(4, 8, 24, 16))
    elif kind == MODE_EXTERNAL:
        p.setBrush(C_EXTERNAL_FILL)
        p.drawRect(QRectF(10, 10, 12, 12))
    elif kind == MODE_COMMENT:           # a bare "T": text with no frame
        p.setPen(QPen(C_TEXT, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawLine(QLineF(8, 8.5, 24, 8.5))
        p.drawLine(QLineF(16, 8.5, 16, 25))
    elif kind == MODE_DOCUMENT:
        p.setBrush(C_DOC_FILL)
        p.drawPolygon(QPolygonF([QPointF(11, 6), QPointF(27, 6), QPointF(27, 26),
                                 QPointF(5, 26), QPointF(5, 12)]))
        p.setBrush(C_DOC_FOLD)
        p.drawPolygon(QPolygonF([QPointF(11, 6), QPointF(11, 12), QPointF(5, 12)]))
    elif kind == MODE_CONNECT:
        p.setBrush(C_PROCESS_FILL)
        p.drawRect(QRectF(2, 18, 11, 9))
        p.setBrush(C_DOC_FILL)
        p.drawRect(QRectF(19, 5, 11, 9))
        p.setPen(QPen(C_ARROW, 2))
        p.setBrush(C_ARROW)
        p.drawLine(QLineF(8, 18, 22, 15))
        p.drawPolygon(QPolygonF([QPointF(24, 14.5), QPointF(17.5, 11.5),
                                 QPointF(18.5, 18.5)]))
    p.end()
    return QIcon(pm)


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
MODE_HINTS = {
    MODE_SELECT: "Select: drag to move, drag handles to resize (also on a selected "
                 "connection), double-click or F2 to rename, Del to delete.",
    MODE_PROCESS: "Click on the canvas to place a process, then type its name (Esc to cancel).",
    MODE_DOCUMENT: "Click on the canvas to place a document, then type its name (Esc to cancel).",
    MODE_EXTERNAL: "Click on the canvas to place an external process (one connection only), "
                   "then type its name (Esc to cancel).",
    MODE_COMMENT: "Click on the canvas to place a text comment (no border, cannot be "
                  "connected), then type its text (Esc to cancel).",
    MODE_CONNECT: "Connect: drag (or click) from a process to a document "
                  "(output) or from a document to a process (input).",
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.scene = DiagramScene(self)
        self.view = DiagramView(self.scene)
        self.panel = ProcessTablePanel(self.scene)
        self.panel.hide()                         # only shown while a process is selected
        self.files_panel = DocumentFilesPanel(self.scene)
        self.files_panel.hide()                   # only shown while a document is selected
        self._panel_height = DEFAULT_PANEL_HEIGHT
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.view)
        self.splitter.addWidget(self.panel)       # both panels sit under the diagram;
        self.splitter.addWidget(self.files_panel)  # at most one of them is visible
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self.splitter)
        self.file_path: Path | None = None
        self.roles_window: RolesWindow | None = None   # created on first use

        self.hint_label = QLabel()
        self.statusBar().addPermanentWidget(self.hint_label)

        self._build_actions()
        self._build_menus_and_toolbar()

        self.scene.modeChanged.connect(self._on_mode_changed)
        self.scene.message.connect(self._show_message)
        self.scene.dirtyChanged.connect(lambda _: self._update_title())
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.scene.contentChanged.connect(self.panel.on_content_changed)
        self.scene.contentChanged.connect(self.files_panel.on_content_changed)
        self.scene.rolesChanged.connect(self.panel.on_content_changed)
        self.panel.rolesRequested.connect(self.show_roles)
        self.splitter.splitterMoved.connect(self._remember_panel_height)

        self._on_mode_changed(MODE_SELECT)
        self._update_title()
        self.resize(1200, 800)

    # ---- actions ------------------------------------------------------------ #
    def _act(self, text, slot, shortcut=None, checkable=False, icon=None) -> QAction:
        a = QAction(text, self)
        if icon is not None:
            a.setIcon(icon)
        if shortcut is not None:
            if isinstance(shortcut, (list, tuple)):
                a.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        return a

    def _build_actions(self) -> None:
        S = self._act
        self.a_new = S("&New", self.new_file, QKeySequence.StandardKey.New)
        self.a_open = S("&Open\u2026", self.open_file, QKeySequence.StandardKey.Open)
        self.a_save = S("&Save", self.save_file, QKeySequence.StandardKey.Save)
        self.a_save_as = S("Save &As\u2026", self.save_file_as,
                           QKeySequence.StandardKey.SaveAs)
        self.a_png = S("Export as &PNG\u2026", self.export_png)
        self.a_svg = S("Export as S&VG\u2026", self.export_svg)
        self.a_report_roles = S("&Roles\u2026", lambda: self.export_report("roles"))
        self.a_report_docs = S("&Documents\u2026", lambda: self.export_report("documents"))
        self.a_quit = S("&Quit", self.close, QKeySequence.StandardKey.Quit)

        self.a_edit = S("&Rename", self.scene.edit_selected_label, "F2")
        self.a_delete = S("&Delete", self.scene.delete_selected,
                          [QKeySequence.StandardKey.Delete, "Backspace"])
        self.a_select_all = S("Select &all", self._select_all,
                              QKeySequence.StandardKey.SelectAll)
        self.a_reset_route = S("Reset connection &routing",
                               self.scene.reset_selected_routes, "Ctrl+R")
        self.a_roles = S("Roles &dictionary\u2026", self.show_roles, "Ctrl+Shift+R")

        self.a_zoom_in = S("Zoom &in", lambda: self.view.zoom(1.25),
                           QKeySequence.StandardKey.ZoomIn)
        self.a_zoom_out = S("Zoom &out", lambda: self.view.zoom(0.8),
                            QKeySequence.StandardKey.ZoomOut)
        self.a_zoom_reset = S("&Reset zoom", self.view.reset_zoom, "Ctrl+0")
        self.a_zoom_fit = S("Zoom to &fit", self.view.zoom_to_fit, "Ctrl+9")
        self.a_grid = S("Show &grid", self._toggle_grid, checkable=True)
        self.a_grid.setChecked(True)
        self.a_snap = S("&Snap to grid", self._toggle_snap, checkable=True)
        self.a_snap.setChecked(True)

        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_actions: dict[str, QAction] = {}
        for mode, label, key in (
                (MODE_SELECT, "Select", "V"),
                (MODE_PROCESS, "Process", "P"),
                (MODE_DOCUMENT, "Document", "D"),
                (MODE_EXTERNAL, "External", "E"),
                (MODE_COMMENT, "Comment", "T"),
                (MODE_CONNECT, "Connect", "C")):
            a = S(label, lambda _=False, m=mode: self.scene.set_mode(m), key,
                  checkable=True, icon=make_icon(mode))
            a.setToolTip(f"{label} ({key})")
            self.mode_group.addAction(a)
            self.mode_actions[mode] = a

    def _build_menus_and_toolbar(self) -> None:
        m = self.menuBar().addMenu("&File")
        for a in (self.a_new, self.a_open, self.a_save, self.a_save_as):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_png)
        m.addAction(self.a_svg)
        reports = m.addMenu("&Reports")
        reports.addAction(self.a_report_roles)
        reports.addAction(self.a_report_docs)
        m.addSeparator()
        m.addAction(self.a_quit)

        m = self.menuBar().addMenu("&Edit")
        for a in (self.a_edit, self.a_delete, self.a_reset_route, self.a_select_all):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_roles)
        m.addSeparator()
        for a in self.mode_actions.values():
            m.addAction(a)

        m = self.menuBar().addMenu("&View")
        for a in (self.a_zoom_in, self.a_zoom_out, self.a_zoom_reset,
                  self.a_zoom_fit):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_grid)
        m.addAction(self.a_snap)

        tb = QToolBar("Tools")
        tb.setMovable(False)
        tb.setIconSize(QSize(28, 28))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(tb)
        for a in self.mode_actions.values():
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_delete)
        tb.addSeparator()
        tb.addAction(self.a_zoom_fit)

    # ---- slots -------------------------------------------------------------- #
    def _on_selection_changed(self) -> None:
        """Under the diagram: the process table while exactly one process (not
        an external process) is selected, the list of files while exactly one
        document is selected; nothing for anything else."""
        try:
            items = self.scene.selectedItems()
        except RuntimeError:
            return
        sel = items[0] if len(items) == 1 else None
        proc = sel if isinstance(sel, ProcessItem) else None
        docu = sel if isinstance(sel, DocumentItem) else None
        self.panel.set_process(proc)
        self.files_panel.set_document(docu)
        shown = self.panel if proc is not None else (
            self.files_panel if docu is not None else None)
        for w in (self.panel, self.files_panel):
            if w is not shown:
                w.hide()
        if shown is None:
            return
        if not shown.isVisible():
            shown.show()
            total = self.splitter.height() or sum(self.splitter.sizes()) or 600
            h = min(self._panel_height, max(140, total // 2))
            self.splitter.setSizes([max(total - h, 120)]
                                   + [h if w is shown else 0
                                      for w in (self.panel, self.files_panel)])
        QTimer.singleShot(0, lambda: self._reveal(sel))

    def show_roles(self) -> None:
        """Open (or bring to the front) the separate Roles dictionary window."""
        if self.roles_window is None:
            self.roles_window = RolesWindow(self.scene, self)
        self.roles_window.show()
        self.roles_window.raise_()
        self.roles_window.activateWindow()

    def _reveal(self, item) -> None:
        """Scroll so that the selected item is not hidden behind the panel."""
        try:
            self.view.ensureVisible(item)
        except RuntimeError:              # the item was deleted meanwhile
            pass

    def _remember_panel_height(self, *_args) -> None:
        for w in (self.panel, self.files_panel):
            if w.isVisible():
                h = self.splitter.sizes()[self.splitter.indexOf(w)]
                if h > 60:
                    self._panel_height = h

    def _on_mode_changed(self, mode: str) -> None:
        self.mode_actions[mode].setChecked(True)
        self.hint_label.setText(MODE_HINTS[mode])

    def _show_message(self, text: str, is_error: bool) -> None:
        self.statusBar().showMessage(text, 7000)
        if is_error:
            QToolTip.showText(QCursor.pos(), text, self.view)

    def _select_all(self) -> None:
        if self.scene.mode == MODE_SELECT:
            for item in self.scene.items():
                item.setSelected(True)

    def _toggle_grid(self, checked: bool) -> None:
        self.scene.show_grid = checked
        self.scene.update()

    def _toggle_snap(self, checked: bool) -> None:
        self.scene.snap = checked

    def _update_title(self) -> None:
        name = self.file_path.name if self.file_path else "Untitled"
        star = "*" if self.scene.dirty else ""
        self.setWindowTitle(f"{name}{star} \u2013 {APP_NAME}")

    # ---- file handling ------------------------------------------------------ #
    def _confirm_discard(self) -> bool:
        if not self.scene.dirty:
            return True
        box = QMessageBox.question(
            self, APP_NAME, "The diagram has unsaved changes. Save them first?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if box == QMessageBox.StandardButton.Save:
            return self.save_file()
        return box == QMessageBox.StandardButton.Discard

    def new_file(self) -> None:
        if self._confirm_discard():
            self.scene.reset()
            self.file_path = None
            self._update_title()

    def open_file(self) -> None:
        if not self._confirm_discard():
            return
        name, _ = QFileDialog.getOpenFileName(self, "Open diagram", "", OPEN_FILTER)
        if not name:
            return
        store = self.scene.store
        files: dict = {}
        try:
            data, files = read_archive(name, store)
            missing = self.scene.load_dict(data, files)
        except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
            for p in files.values():          # nothing was loaded: drop the extracted files
                store.discard(p)
            QMessageBox.critical(self, APP_NAME, f"Could not open file:\n{exc!r}")
            return
        self.file_path = Path(name)
        self.scene.set_dirty(False)
        self._update_title()
        if self.scene.nodes():
            self.view.centerOn(self.scene.itemsBoundingRect().center())
        if missing:
            QMessageBox.warning(
                self, APP_NAME, f"{missing} attached file(s) listed in the diagram are "
                "missing from the archive and were skipped.")

    def save_file(self) -> bool:
        # a legacy .json diagram is saved as a new .bpmn file
        if self.file_path is None or self.file_path.suffix.lower() != FILE_EXT:
            return self.save_file_as()
        return self._write(self.file_path)

    def save_file_as(self) -> bool:
        start = str(self.file_path.with_suffix(FILE_EXT)) if self.file_path else ""
        name, _ = QFileDialog.getSaveFileName(self, "Save diagram", start, FILE_FILTER)
        if not name:
            return False
        path = Path(name)
        if path.suffix.lower() != FILE_EXT:
            path = (path.with_suffix(FILE_EXT) if path.suffix.lower() in ("", ".json")
                    else path.with_name(path.name + FILE_EXT))
        return self._write(path)

    def _write(self, path: Path) -> bool:
        try:
            files: dict = {}
            data = self.scene.to_dict(files)
            write_archive(path, data, files)
        except (OSError, tarfile.TarError) as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not save file:\n{exc}")
            return False
        self.file_path = path
        self.scene.set_dirty(False)
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}", 5000)
        return True

    def _export(self, title: str, filt: str, suffix: str, func) -> None:
        if not self.scene.nodes():
            QMessageBox.information(self, APP_NAME, "The diagram is empty.")
            return
        name, _ = QFileDialog.getSaveFileName(self, title, "", filt)
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        if func(str(path)):
            self.statusBar().showMessage(f"Exported {path}", 5000)
        else:
            QMessageBox.warning(self, APP_NAME, "Export failed.")

    def export_png(self) -> None:
        self._export("Export PNG", "PNG image (*.png)", ".png", self.scene.export_png)

    def export_svg(self) -> None:
        if QSvgGenerator is None:
            QMessageBox.warning(self, APP_NAME, "QtSvg is not available.")
            return
        self._export("Export SVG", "SVG image (*.svg)", ".svg", self.scene.export_svg)

    def export_report(self, kind: str) -> None:
        """File > Reports: build the report, ask where to save it, write it."""
        if kind == "roles":
            if not len(self.scene.roles):
                QMessageBox.information(
                    self, APP_NAME, "The Roles dictionary is empty - there is nothing to "
                    "report yet.\nAdd roles with Edit > Roles dictionary.")
                return
            report = roles_report(self.scene.roles)
        else:
            report = documents_report(self.scene.nodes(), self.scene.roles)
            if not report.rows:
                QMessageBox.information(
                    self, APP_NAME, "No document is connected to a process yet - there is "
                    "nothing to report.")
                return
        stem = self.file_path.stem if self.file_path else "diagram"
        start = f"{stem}-{kind}.html"
        if self.file_path:
            start = str(self.file_path.with_name(start))
        name, chosen = QFileDialog.getSaveFileName(
            self, f"Export report: {report.title}", start, REPORT_FILTER)
        if not name:
            return
        path, fmt = report_target(name, chosen)
        source = self.file_path.name if self.file_path else "Untitled"
        try:
            if fmt == "csv":
                write_text_atomic(path, report_csv(report), "utf-8-sig")
            else:
                when = datetime.now().strftime("%Y-%m-%d %H:%M")
                write_text_atomic(path, report_html(report, source, when), "utf-8")
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not save the report:\n{exc}")
            return
        self.statusBar().showMessage(f"Saved report {path}", 5000)

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            self.scene.store.cleanup()       # delete the session copies of attachments
            if self.roles_window is not None:
                self.roles_window.close()
            event.accept()
        else:
            event.ignore()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
