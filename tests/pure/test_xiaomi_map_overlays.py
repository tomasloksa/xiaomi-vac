"""Pure-tier tests for the xiaomi-JSON-brand map overlays added alongside
Atlas-card support for this model family: carpets, the traveled-path trail,
and the mm->metre scale conversion `vector_map()` needs for this brand.

No homeassistant import — see conftest.py for how `xvac.map`/`map_vector`
get loaded standalone.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import map_vector
from xvac.map import MapFetcher


# --- MapFetcher._parse_carpets --------------------------------------------
def test_parse_carpets_extracts_rectangles():
    blob = json.dumps({"carpets": [
        {"p": [0, 0, 1000, 0, 1000, 1000, 0, 1000], "d": "c1"},
        {"p": [2000, 2000, 2500, 2000, 2500, 2500, 2000, 2500], "d": "c2"},
    ]})
    out = MapFetcher._parse_carpets(blob)
    assert out == [
        [0, 0, 1000, 0, 1000, 1000, 0, 1000],
        [2000, 2000, 2500, 2000, 2500, 2500, 2000, 2500],
    ]


def test_parse_carpets_missing_or_malformed_returns_empty():
    assert MapFetcher._parse_carpets(json.dumps({})) == []
    assert MapFetcher._parse_carpets(json.dumps({"carpets": [{"p": [1, 2]}]})) == []  # short p
    assert MapFetcher._parse_carpets("not json") == []


# --- MapFetcher._parse_path ------------------------------------------------
def _point(x, y, type_=1):
    return {"x": x, "y": y, "type": type_, "sweep_mop_mode": 0, "yaw": 0}


def _path_blob(points):
    return json.dumps({"paths": {"pose_id": 1, "points": json.dumps(points)}})


def test_parse_path_splits_on_type_zero():
    """A `type:0` point starts a brand-new, disconnected segment — never
    joined to whatever came before it (the bug a real user caught: joining
    every point into one line drew straight cuts through walls between
    legs)."""
    points = [
        _point(1, 1, 1), _point(10, 0, 1), _point(20, 0, 1),   # leg 1 (3 pts)
        _point(500, 500, 0), _point(510, 500, 1),               # leg 2 (2 pts, new leg starts here)
    ]
    segments = MapFetcher._parse_path(_path_blob(points))
    assert segments == [
        [(1, 1), (10, 0), (20, 0)],
        [(500, 500), (510, 500)],
    ]


def test_parse_path_strips_zero_sentinel_buffer():
    """The raw array is a fixed-size preallocated buffer; unwritten slots are
    literal (0,0) sentinels forming one contiguous run — keep only the
    longest contiguous run of real (non 0,0) points."""
    sentinels = [_point(0, 0, 0)] * 5
    real = [_point(1, 1, 1), _point(2, 2, 1), _point(3, 3, 1)]
    segments = MapFetcher._parse_path(_path_blob(sentinels + real))
    assert segments == [[(1, 1), (2, 2), (3, 3)]]


def test_parse_path_drops_single_point_segments():
    """A segment needs >=2 points to be drawable as a line."""
    points = [
        _point(1, 1, 1), _point(10, 0, 1),   # real 2-point leg
        _point(999, 999, 0),                  # new leg with only one point ever recorded
    ]
    segments = MapFetcher._parse_path(_path_blob(points))
    assert segments == [[(1, 1), (10, 0)]]


def test_parse_path_missing_or_malformed_returns_empty():
    assert MapFetcher._parse_path(json.dumps({})) == []
    assert MapFetcher._parse_path("not json") == []
    assert MapFetcher._parse_path(json.dumps({"paths": {"points": "not an array"}})) == []


# --- MapFetcher._mm_to_pixel_from_calibration ------------------------------
def test_mm_to_pixel_from_calibration_builds_correct_affine():
    # Three points relating a simple 1:1 vacuum(mm)->map(px) mapping, offset
    # by (100, 200), with the y-axis inverted (as real calibration data is).
    calibration = [
        {"vacuum": {"x": 0, "y": 0}, "map": {"x": 100, "y": 200}},
        {"vacuum": {"x": 10, "y": 0}, "map": {"x": 110, "y": 200}},
        {"vacuum": {"x": 0, "y": 10}, "map": {"x": 100, "y": 190}},
    ]
    transform = MapFetcher._mm_to_pixel_from_calibration(calibration)
    assert transform is not None
    assert transform(0, 0) == (100, 200)
    assert transform(10, 0) == (110, 200)
    assert transform(0, 10) == (100, 190)
    assert transform(5, 5) == (105, 195)


def test_mm_to_pixel_from_calibration_missing_points_returns_none():
    assert MapFetcher._mm_to_pixel_from_calibration([]) is None
    assert MapFetcher._mm_to_pixel_from_calibration([{"vacuum": {"x": 0, "y": 0}, "map": {"x": 0, "y": 0}}]) is None


# --- map_vector.vector_map: scale / carpets / path -------------------------
def _fake_md_with_path():
    room = SimpleNamespace(name="Kitchen", pos_x=1000.0, pos_y=2000.0,
                            x0=0.0, y0=0.0, x1=3000.0, y1=4000.0)
    sub_path = [SimpleNamespace(x=0.0, y=0.0), SimpleNamespace(x=1000.0, y=1000.0)]
    wall = SimpleNamespace(x0=0.0, y0=0.0, x1=1000.0, y1=0.0)
    return SimpleNamespace(
        path=SimpleNamespace(path=[sub_path]),
        charger=SimpleNamespace(x=500.0, y=-500.0), vacuum_position=None,
        goto=None, rooms={3: room}, walls=[wall],
        no_go_areas=[], no_mopping_areas=[], zones=[],
        vacuum_room=None, vacuum_room_name=None,
    )


def test_vector_map_scale_converts_mm_to_metres():
    """xiaomi-brand callers pass scale=0.001 (mm->m) since the card's SVG
    assumes metre-scale constants — confirmed bug: without this, a room's
    bbox came out ~10700x5900 unscaled, a "10km-wide room"."""
    out = map_vector.vector_map(_fake_md_with_path(), b"", ijai_grid=False, scale=0.001)

    assert out["charger"] == {"x": 0.5, "y": -0.5}
    assert out["rooms"][0]["cx"] == 1.0
    assert out["rooms"][0]["cy"] == 2.0
    assert out["rooms"][0]["bbox"] == [0.0, 0.0, 3.0, 4.0]
    assert out["walls"] == [[0.0, 0.0, 1.0, 0.0]]


def test_vector_map_path_param_takes_priority_and_stays_segmented():
    """Explicit `path=` (xiaomi's own segment-split trajectory) wins over
    `md.path`, and the output is always a list of segments — never a flat
    point list (that shape silently drew impossible-looking straight lines
    through walls for both brands before this fix)."""
    explicit_path = [[(0.0, 0.0), (1000.0, 0.0)], [(2000.0, 2000.0), (2500.0, 2000.0)]]
    out = map_vector.vector_map(
        _fake_md_with_path(), b"", ijai_grid=False, scale=0.001, path=explicit_path,
    )
    assert out["path"] == [[[0.0, 0.0], [1.0, 0.0]], [[2.0, 2.0], [2.5, 2.0]]]


def test_vector_map_falls_back_to_md_path_as_segments():
    """When no explicit `path=` is given, `md.path.path` (ijai's own already
    sub-path-shaped data) is used — also scaled, also kept as segments (this
    was a latent bug: previously flattened into one line, same class of bug
    as xiaomi's, just never noticed because ijai already is metre-scale)."""
    out = map_vector.vector_map(_fake_md_with_path(), b"", ijai_grid=False, scale=1.0)
    assert out["path"] == [[[0.0, 0.0], [1000.0, 1000.0]]]


def test_vector_map_carpets_scaled():
    carpets = [[0, 0, 1000, 0, 1000, 1000, 0, 1000]]
    out = map_vector.vector_map(_fake_md_with_path(), b"", ijai_grid=False, scale=0.001, carpets=carpets)
    assert out["carpets"] == [[0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]]


def test_vector_map_no_carpets_key_when_none_given():
    out = map_vector.vector_map(_fake_md_with_path(), b"", ijai_grid=False, scale=0.001)
    assert "carpets" not in out


def test_vector_map_xiaomi_grid_merged_into_output():
    xg = {"size": {"x": 2, "y": 2}, "bounds": {"minX": 0, "minY": 0, "maxX": 1, "maxY": 1},
          "resolution": 0.5, "grid_rle": [0, 4], "legend": {"room_min": 1, "room_max": 6}}
    out = map_vector.vector_map(_fake_md_with_path(), b"", ijai_grid=False, xiaomi_grid=xg)
    assert out["grid_rle"] == [0, 4]
    assert out["legend"]["room_min"] == 1


# --- room ids: grid_id vs room_id ------------------------------------------
# The grid cell value, `rooms[].id` and the `clean_segment` argument are all the
# same number. Hardware-confirmed on ov21gl: all 8 rooms report `room_id: 0` —
# the grid's own "outside" marker — so remapping through it erased every room
# cell. ov42gl reports real ids, so both layouts have to work.
def _grid_blob(map_room_info, room_attrs=None):
    """6x4 grid: wall border, room grid_id 3 at cols 1-2, grid_id 4 at cols 3-4."""
    import base64
    import zlib

    w, h = 6, 4
    g = bytearray([1] * (w * h))
    for row in (1, 2):
        for col in (1, 2):
            g[row * w + col] = 3
        for col in (3, 4):
            g[row * w + col] = 4
    return json.dumps({
        "width": w, "height": h, "resolution": 50, "origin_x": 0, "origin_y": 0,
        "map_data": base64.b64encode(zlib.compress(bytes(g))).decode(),
        "map_room_info": map_room_info,
        "room_attrs": room_attrs if room_attrs is not None else [
            {"id": 3, "room_name": "Bath", "name_pos_x": 100, "name_pos_y": 100},
            {"id": 4, "room_name": "", "name_pos_x": 200, "name_pos_y": 100},
        ],
    })


def _rle_hist(rle):
    h = {}
    for i in range(0, len(rle), 2):
        h[rle[i]] = h.get(rle[i], 0) + rle[i + 1]
    return h


def test_usable_room_ids_rejects_zero_and_duplicates():
    assert MapFetcher._usable_room_ids({3: 11, 4: 12}) is True
    assert MapFetcher._usable_room_ids({3: 0, 4: 0}) is False      # ov21gl
    assert MapFetcher._usable_room_ids({3: 0, 4: 12}) is False     # 0 == "outside"
    assert MapFetcher._usable_room_ids({3: 5, 4: 5}) is False      # two rooms, one label
    assert MapFetcher._usable_room_ids({}) is False


def test_parse_xiaomi_grid_keeps_rooms_when_room_id_is_zero():
    """An all-zero room_id table is ignored: grid_id stays the room id, so the
    cells survive normalisation and every room stays selectable."""
    out = MapFetcher._parse_xiaomi_grid(_grid_blob([
        {"grid_id": 3, "room_id": 0}, {"grid_id": 4, "room_id": 0},
    ]))
    hist = _rle_hist(out["grid_rle"])
    assert hist.get(3) == 4 and hist.get(4) == 4   # not erased to 0
    assert [r["id"] for r in out["rooms"]] == [3, 4]
    lg = out["legend"]
    assert all(lg["room_min"] <= r["id"] <= lg["room_max"] for r in out["rooms"])


def test_parse_xiaomi_grid_honours_usable_room_ids():
    """When room_id identifies rooms it wins, and the grid labels follow so
    cell value and `rooms[].id` still agree."""
    out = MapFetcher._parse_xiaomi_grid(_grid_blob([
        {"grid_id": 3, "room_id": 11}, {"grid_id": 4, "room_id": 12},
    ]))
    hist = _rle_hist(out["grid_rle"])
    assert hist.get(11) == 4 and hist.get(12) == 4
    assert 3 not in hist and 4 not in hist
    assert [r["id"] for r in out["rooms"]] == [11, 12]


def test_parse_xiaomi_grid_rooms_carry_extent_and_labels():
    """bbox is the room's cell extent in metres; name/anchor come from
    `room_attrs`, matched on the id the grid uses. An empty room_name becomes
    None so the card falls back to "Room N"."""
    out = MapFetcher._parse_xiaomi_grid(_grid_blob([
        {"grid_id": 3, "room_id": 0}, {"grid_id": 4, "room_id": 0},
    ]))
    bath, unnamed = out["rooms"]
    assert bath["name"] == "Bath" and unnamed["name"] is None
    assert (bath["cx"], bath["cy"]) == (0.1, 0.1)
    # cols 1-2, rows 1-2 at 50mm/cell from origin 0 -> 0.05..0.15 m, far edge inclusive
    assert bath["bbox"] == [0.05, 0.05, 0.15, 0.15]
    assert unnamed["bbox"] == [0.15, 0.05, 0.25, 0.15]


def test_vector_map_keeps_xiaomi_grid_rooms():
    """`md.rooms` collapses to one entry under a shared room_id, so the
    grid-derived list wins whenever it is present."""
    xg = MapFetcher._parse_xiaomi_grid(_grid_blob([
        {"grid_id": 3, "room_id": 0}, {"grid_id": 4, "room_id": 0},
    ]))
    out = map_vector.vector_map(
        _fake_md_with_path(), b"", ijai_grid=False, scale=0.001, xiaomi_grid=xg,
    )
    assert [r["id"] for r in out["rooms"]] == [3, 4]


def test_vector_map_tolerates_room_without_label_position():
    """`pos_x`/`pos_y` are None when a room has no label; scaling that must not
    raise (map.py swallows it as "parser rejected map frame", dropping the
    whole map)."""
    room = SimpleNamespace(name=None, pos_x=None, pos_y=None,
                           x0=1.0, y0=2.0, x1=3.0, y1=4.0)
    md = SimpleNamespace(
        path=None, charger=None, vacuum_position=None, goto=None, rooms={5: room},
        walls=[], no_go_areas=[], no_mopping_areas=[], zones=[],
        vacuum_room=None, vacuum_room_name=None,
    )
    out = map_vector.vector_map(md, b"", ijai_grid=False, scale=0.001)
    assert out["rooms"][0]["cx"] is None
    assert out["rooms"][0]["bbox"] == [0.001, 0.002, 0.003, 0.004]


# --- room_chains: tap targets that follow the real room shape ---------------
def _l_shaped_blob():
    """8x6 grid. Room 3 is L-shaped; room 4 sits in the notch of that L, so
    room 3's bounding RECTANGLE completely contains room 4 — the overlap that
    made bbox tap targets pick the wrong room."""
    import base64
    import zlib

    w, h = 8, 6
    g = bytearray([1] * (w * h))
    for row in range(1, 5):          # room 3: full-height left column ...
        for col in range(1, 3):
            g[row * w + col] = 3
    for col in range(3, 7):          # ... plus a foot along the bottom row
        g[1 * w + col] = 3
    for row in range(2, 5):          # room 4: tucked into the notch above
        for col in range(3, 7):
            g[row * w + col] = 4
    return json.dumps({
        "width": w, "height": h, "resolution": 50, "origin_x": 0, "origin_y": 0,
        "map_data": base64.b64encode(zlib.compress(bytes(g))).decode(),
        "map_room_info": [{"grid_id": 3, "room_id": 0}, {"grid_id": 4, "room_id": 0}],
        "room_attrs": [],
    })


def test_parse_xiaomi_grid_traces_room_chains():
    """One chain per room, ids matching `rooms[].id` — the card prefers these
    over bbox rectangles for its fills and tap targets."""
    out = MapFetcher._parse_xiaomi_grid(_l_shaped_blob())
    assert [c["id"] for c in out["room_chains"]] == [3, 4]
    assert [r["id"] for r in out["rooms"]] == [3, 4]


def test_room_chain_follows_shape_where_bbox_overlaps():
    """The L-shaped room's bbox swallows its neighbour, so rectangles cannot
    tell the two apart; its traced outline has the L's 6 corners, not 4."""
    out = MapFetcher._parse_xiaomi_grid(_l_shaped_blob())
    by_id = {r["id"]: r for r in out["rooms"]}
    l_box, inner_box = by_id[3]["bbox"], by_id[4]["bbox"]
    # room 3's rectangle fully contains room 4's
    assert l_box[0] <= inner_box[0] and l_box[1] <= inner_box[1]
    assert l_box[2] >= inner_box[2] and l_box[3] >= inner_box[3]

    rings = {c["id"]: c["rings"] for c in out["room_chains"]}
    assert len(rings[3]) == 1 and len(rings[3][0]) == 6   # L, not a rectangle
    assert len(rings[4]) == 1 and len(rings[4][0]) == 4   # this one really is


# --- label anchors bridge the grid's ids and the device's -------------------
def _shifted_id_blob():
    """The ov21gl case: grid regions are 3 and 4, but `room_attrs` calls those
    same rooms 7 and 8 (device ids), with `map_room_info` all zeros. The label
    anchors are the only link: id 7's anchor sits in region 3, id 8's in 4."""
    import base64
    import zlib

    w, h = 6, 4
    g = bytearray([1] * (w * h))
    for row in (1, 2):
        for col in (1, 2):
            g[row * w + col] = 3
        for col in (3, 4):
            g[row * w + col] = 4
    return json.dumps({
        "width": w, "height": h, "resolution": 50, "origin_x": 0, "origin_y": 0,
        "map_data": base64.b64encode(zlib.compress(bytes(g))).decode(),
        "map_room_info": [{"grid_id": 3, "room_id": 0}, {"grid_id": 4, "room_id": 0}],
        "room_attrs": [
            {"id": 7, "room_name": "Kitchen", "name_pos_x": 100, "name_pos_y": 100},
            {"id": 8, "room_name": "Bedroom", "name_pos_x": 200, "name_pos_y": 100},
        ],
    })


def test_label_anchor_maps_grid_ids_to_device_room_ids():
    """Selecting a room must send the id the DEVICE knows it by, so the grid is
    relabelled through the anchors: region 3 becomes 7, region 4 becomes 8."""
    out = MapFetcher._parse_xiaomi_grid(_shifted_id_blob())
    assert [r["id"] for r in out["rooms"]] == [7, 8]
    assert [r["name"] for r in out["rooms"]] == ["Kitchen", "Bedroom"]
    hist = _rle_hist(out["grid_rle"])
    assert hist.get(7) == 4 and hist.get(8) == 4      # cells carry the device id
    assert 3 not in hist and 4 not in hist
    # ...so the raster, the tap target and clean_segment all agree
    assert [c["id"] for c in out["room_chains"]] == [7, 8]


def test_label_anchor_ignored_when_map_room_info_is_usable():
    """`map_room_info` stays authoritative where it works (ov42gl), so that
    hardware-verified path is untouched by the anchor fallback."""
    blob = json.loads(_shifted_id_blob())
    blob["map_room_info"] = [{"grid_id": 3, "room_id": 11}, {"grid_id": 4, "room_id": 12}]
    out = MapFetcher._parse_xiaomi_grid(json.dumps(blob))
    assert [r["id"] for r in out["rooms"]] == [11, 12]


def test_label_anchor_rejected_when_a_label_misses_its_room():
    """A label parked on a wall (or two labels in one room) makes the mapping
    unsafe — fall back to grid ids rather than guess half of it."""
    blob = json.loads(_shifted_id_blob())
    blob["room_attrs"][1]["name_pos_x"] = 0      # on the wall border, not a room
    out = MapFetcher._parse_xiaomi_grid(json.dumps(blob))
    assert [r["id"] for r in out["rooms"]] == [3, 4]
