"""Guard (AST, без sentry_sdk): ПД не попадают в лог-вызовы и уведомления разработчику.

Проверяются app/**/*.py и main.py.
  (a) у error/exception/critical первый аргумент это строковая константа
      (не f-строка, не Call, не BinOp/%-форматирование): итоговый текст попадает в
      message события Sentry и в Telegram-алерт, поэтому шаблон должен быть константным;
  (b) ни один лог-вызов любого уровня не использует fio, full_name, custom_position,
      caption, username, first_name, last_name (обёртки len()/bool() допустимы);
  (c) в notify_mirror_failure/_notify_mirror_failure текст не содержит этих имён
      (в том числе внутри f-строки; обёртки len()/bool() допустимы).
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LEVELS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}
ERROR_LEVELS = {"error", "exception", "critical"}
DEFAULT_LOGGERS = {"logger", "error_logger", "log", "logging", "_logger", "LOGGER"}
PII_NAMES = {"fio", "full_name", "custom_position", "caption", "username", "first_name", "last_name"}
MIRROR_FUNCS = {"notify_mirror_failure", "_notify_mirror_failure"}


def _source_files():
    files = sorted(p for p in (ROOT / "app").rglob("*.py") if "__pycache__" not in p.parts)
    files.append(ROOT / "main.py")
    return files


def _aliases(tree):
    names = set(DEFAULT_LOGGERS)
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
            fn = n.value.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "getLogger") or (
                isinstance(fn, ast.Name) and fn.id == "getLogger"
            ):
                names.update(t.id for t in n.targets if isinstance(t, ast.Name))
    return names


def _is_log_call(node, aliases):
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in LEVELS):
        return False
    base = node.func.value
    if isinstance(base, ast.Name) and base.id in aliases:
        return True
    if isinstance(base, ast.Attribute) and base.attr in aliases:
        return True
    return (isinstance(base, ast.Call) and isinstance(base.func, ast.Attribute)
            and base.func.attr == "getLogger")


def _log_calls(tree):
    aliases = _aliases(tree)
    return [n for n in ast.walk(tree) if _is_log_call(n, aliases)]


def _pii_names(node):
    """Имена ПД внутри выражения; содержимое len(...)/bool(...) не учитывается."""
    found = []

    def visit(n):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("len", "bool"):
            return
        if isinstance(n, ast.Name) and n.id in PII_NAMES:
            found.append(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in PII_NAMES:
            found.append(n.attr)
        elif (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
              and n.slice.value in PII_NAMES):
            found.append(n.slice.value)
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
              and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value in PII_NAMES):
            found.append(n.args[0].value)
        for child in ast.iter_child_nodes(n):
            visit(child)

    visit(node)
    return found


def _call_arguments(call):
    return list(call.args) + [k.value for k in call.keywords]


# --- правила (на вход: имя файла для сообщений и AST) ---

def violations_constant_template(tree, rel):
    out = []
    for call in _log_calls(tree):
        if call.func.attr not in ERROR_LEVELS:
            continue
        first = call.args[0] if call.args else None
        if first is None or (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        out.append(f"{rel}:{call.lineno}: [{call.func.attr}] первый аргумент {type(first).__name__}, "
                   f"нужна строковая константа")
    return out


def violations_pii_in_logs(tree, rel):
    out = []
    for call in _log_calls(tree):
        names = sorted({n for a in _call_arguments(call) for n in _pii_names(a)})
        if names:
            out.append(f"{rel}:{call.lineno}: [{call.func.attr}] в лог-вызове: {', '.join(names)}")
    return out


def violations_pii_in_mirror(tree, rel):
    out = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        fn = call.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
        if name not in MIRROR_FUNCS:
            continue
        names = sorted({n for a in _call_arguments(call)[1:] for n in _pii_names(a)})
        if names:
            out.append(f"{rel}:{call.lineno}: [{name}] в тексте уведомления: {', '.join(names)}")
    return out


def _run(rule):
    out = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out += rule(tree, path.relative_to(ROOT).as_posix())
    return out


class TestLogPiiGuard:

    def test_error_level_templates_are_string_constants(self):
        found = _run(violations_constant_template)
        assert not found, "\n" + "\n".join(found)

    def test_no_pii_names_in_log_calls(self):
        found = _run(violations_pii_in_logs)
        assert not found, "\n" + "\n".join(found)

    def test_no_pii_names_in_mirror_notifications(self):
        found = _run(violations_pii_in_mirror)
        assert not found, "\n" + "\n".join(found)


class TestGuardDetectors:
    """Детекторы действительно ловят нарушения (guard не пустой)."""

    @staticmethod
    def _tree(code):
        return ast.parse(code)

    def test_constant_template_detects_fstring_call_and_percent(self):
        tree = self._tree(
            "logger.error(f'x {a}')\n"
            "logger.exception(fmt(a))\n"
            "logger.critical('x %s' % a)\n"
            "logger.error('ok %s', a)\n"
            "logger.info(f'допустимо {a}')\n"
        )
        found = violations_constant_template(tree, "f.py")
        assert [f.split(":")[1] for f in found] == ["1", "2", "3"]

    def test_pii_detector_ignores_len_and_bool_wrappers(self):
        tree = self._tree(
            "logger.warning('a %s', len(fio))\n"
            "logger.info('b %s', bool(message.caption))\n"
            "logger.info('c %s', full_name)\n"
            "logging.getLogger('errors').exception('d %s', user['full_name'])\n"
            "logger.info(f'e {message.from_user.username}')\n"
        )
        found = violations_pii_in_logs(tree, "f.py")
        assert [f.split(":")[1] for f in found] == ["3", "4", "5"]

    def test_mirror_detector_sees_names_inside_fstring(self):
        tree = self._tree(
            "await _notify_mirror_failure(bot, f'увольнение {target_id} ({full_name})')\n"
            "await notify_mirror_failure(bot, f'увольнение {target_id}')\n"
            "await notify_mirror_failure(bot, f'{custom_position or 1}')\n"
            "await notify_mirror_failure(bot, f'{bool(custom_position)}')\n"
        )
        found = violations_pii_in_mirror(tree, "f.py")
        assert [f.split(":")[1] for f in found] == ["1", "3"]
