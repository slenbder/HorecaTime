"""scrub_event: события Sentry не содержат ФИО, ввод пользователя и username (без sentry_sdk)."""
import copy

from app.utils.sentry_scrub import scrub_event


def _full_event():
    return {
        "event_id": "abc",
        "level": "error",
        "logger": "app.utils.mirror",
        "logentry": {
            "message": "Не удалось уведомить разработчика: %s",
            "params": ["апрув 1 (Иванов Иван)"],
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "module": "builtins",
                    "value": "boom",
                    "stacktrace": {
                        "frames": [
                            {"function": "outer", "lineno": 10, "vars": {"full_name": "Иванов Иван"}},
                            {"function": "inner", "lineno": 20, "vars": {"message": "<Message text=...>"}},
                        ]
                    },
                },
                {
                    "type": "RuntimeError",
                    "stacktrace": {"frames": [{"function": "cause", "lineno": 5, "vars": {"fio": "Иван"}}]},
                },
            ]
        },
        "user": {"username": "ivan"},
        "request": {"data": "текст"},
        "extra": {"sys.argv": ["main.py"]},
        "breadcrumbs": {"values": [{"message": "x"}]},
    }


class TestScrubEvent:

    def test_logentry_message_kept_params_removed(self):
        event = scrub_event(_full_event())
        assert event["logentry"] == {"message": "Не удалось уведомить разработчика: %s"}

    def test_frame_vars_removed_in_all_exceptions_and_frames(self):
        event = scrub_event(_full_event())
        frames = [
            f
            for v in event["exception"]["values"]
            for f in v["stacktrace"]["frames"]
        ]
        assert len(frames) == 3
        assert all("vars" not in f for f in frames)

    def test_exception_value_removed_type_module_stacktrace_kept(self):
        event = scrub_event(_full_event())
        first, second = event["exception"]["values"]
        assert "value" not in first and "value" not in second
        assert (first["type"], first["module"]) == ("ValueError", "builtins")
        assert second["type"] == "RuntimeError"
        assert [f["function"] for f in first["stacktrace"]["frames"]] == ["outer", "inner"]
        assert [f["function"] for f in second["stacktrace"]["frames"]] == ["cause"]

    def test_user_request_extra_breadcrumbs_removed(self):
        event = scrub_event(_full_event())
        for key in ("user", "request", "extra", "breadcrumbs"):
            assert key not in event

    def test_rest_of_event_intact(self):
        original = _full_event()
        event = scrub_event(copy.deepcopy(original))
        assert event["event_id"] == "abc"
        assert event["level"] == "error"
        assert event["logger"] == "app.utils.mirror"
        values = event["exception"]["values"]
        assert all("value" not in v for v in values)
        assert [(v["type"], v.get("module")) for v in values] == [
            ("ValueError", "builtins"), ("RuntimeError", None),
        ]
        assert [f["function"] for f in values[0]["stacktrace"]["frames"]] == ["outer", "inner"]
        assert [f["lineno"] for f in values[0]["stacktrace"]["frames"]] == [10, 20]

    def test_returns_the_event(self):
        event = _full_event()
        assert scrub_event(event, {"hint": 1}) is event

    def test_empty_event_does_not_fail(self):
        assert scrub_event({}) == {}

    def test_event_without_keys_does_not_fail(self):
        event = {"level": "error"}
        assert scrub_event(event) == {"level": "error"}

    def test_missing_nested_keys_do_not_fail(self):
        event = {
            "logentry": {"message": "m"},
            "exception": {"values": [{"type": "E"}, {"type": "E2", "stacktrace": {}}]},
        }
        assert scrub_event(event) == {
            "logentry": {"message": "m"},
            "exception": {"values": [{"type": "E"}, {"type": "E2", "stacktrace": {}}]},
        }

    def test_none_and_empty_containers_do_not_fail(self):
        event = {"logentry": None, "exception": {"values": None}, "user": None}
        assert scrub_event(event) == {"logentry": None, "exception": {"values": None}}
        assert scrub_event({"exception": None}) == {"exception": None}
        assert scrub_event({"exception": {"values": [{"stacktrace": {"frames": []}}]}}) == {
            "exception": {"values": [{"stacktrace": {"frames": []}}]}
        }
