"""Phase 20 RED — content_scene_reorder bounded policy."""

def test_policy_module_must_exist_and_intent_bounded():
    try:
        import jarvis.core.content_scene_reorder as mod  # noqa: F401
    except ModuleNotFoundError:
        assert False, "module jarvis.core.content_scene_reorder must exist"
    from jarvis.core.content_scene_reorder import admit_reorder
    assert callable(admit_reorder)


def test_admit_reorder_returns_safe_shape():
    from jarvis.core.content_scene_reorder import admit_reorder

    ok = admit_reorder(0, 1, 3)
    assert ok["ok"] is True
    assert ok["intent"] == "content_studio_scene_reorder"
    assert "from_index" in ok and "to_index" in ok
    # must not leak scene content / paths
    assert "path" not in ok and "file" not in ok and "content" not in ok


def test_admit_reorder_rejects_bad_types_and_bounds():
    from jarvis.core.content_scene_reorder import admit_reorder

    assert admit_reorder(True, 1, 3)["ok"] is False
    assert admit_reorder(0, True, 3)["ok"] is False
    assert admit_reorder("0", 1, 3)["ok"] is False
    assert admit_reorder(0, 1, True)["ok"] is False
    assert admit_reorder(-1, 1, 3)["ok"] is False
    assert admit_reorder(0, 5, 3)["ok"] is False
    assert admit_reorder(1, 1, 3)["ok"] is False  # same -> no-op rejected


def test_admit_reorder_must_fail_closed_same_surface_only():
    from jarvis.core.content_scene_reorder import admit_reorder

    # size <=1 cannot reorder
    assert admit_reorder(0, 0, 1)["ok"] is False
    assert admit_reorder(0, 1, 0)["ok"] is False
    # out of range both
    assert admit_reorder(10, 11, 3)["ok"] is False
