# Командний рядок `sipl`

```text
sipl parse FILE [--json] [--strict] [-o OUT]
sipl check FILE [--json] [--strict]
sipl tree  FILE [-f text|json|dot|svg|html] [--notation bnf|math] [--no-spans] [-o OUT]
sipl term  FILE [-f text|ascii|latex] [--explain [steps|chain]] [--json] [--rules]
sipl eval  FILE -s "X=5, Y=2" [--explain] [--max-iterations N] [--json]
sipl prove FILE [--spec SPEC.toml] [--mode partial|total] [--no-z3] [--wp] [--json]
```

`FILE` може бути `-` (стандартний ввід). `--strict` дозволяє лише БНФ курсу.
Для `prove` специфікація за замовчуванням – `FILE.spec.toml` поруч із програмою.
Вивід завжди в UTF-8.

## Коди завершення

| Код | Значення |
|---|---|
| 0 | успіх: розібрано, перевірено, обчислено до стану, доведено |
| 1 | помилка у вхідних даних: синтаксис, стан, специфікація, файл |
| 2 | неправильне використання командного рядка |
| 3 | негативний результат: обчислення невизначене, коректність спростовано або не доведено |
| 4 | результат не визначено: ліміт ітерацій, доведення не вирішене |

## JSON-контракти

Кожен JSON-вивід містить `"ok"`, а успішні – ще й `"schema"` з версією.
Нові поля можуть з'являтися лише зі збільшенням мінорної версії; перейменування
чи видалення полів означає нову схему.

| Команда | `schema` | Основні поля |
|---|---|---|
| `parse --json` | `sipl.ast/1` | `ast`: `{node, category, ..., span}` |
| `check --json` | `sipl.check/1` | `variables`, `assigned`, `loops`, `diagnostics` |
| `tree -f json` | `sipl.derivation/1` | `root`: `{id, kind, label, rule, rule_text, category, span, children}` / `{id, kind: "terminal", text, leaf_index, span}`, `frontier`, `yield_matches_source` |
| `term --json` | `sipl.term/1` | `text`, `latex`, `term`: `{kind, ..., origin}`, `explanation.steps[]`: `{rule, lhs, rhs, whole}` |
| `eval --json` | `sipl.eval/1` | `status`, `initial`, `result`, `reason`, `iterations`, `states`, `trace[]`: `{rule, depth, text, origin, state_in, state_out}` |
| `prove --json` | `sipl.proof/1` | `verdict`, `mode`, `term`, `loops[]`, `conditions[]`: `{kind, loop, formula, status, counterexample, explanation}`, `testing` |

`span`/`origin`: `{start, end, line, column, end_line, end_column}`. Зміщення в
символах; рядки й колонки нумеруються з 1, кінець не входить у діапазон (як в LSP).

Помилка: `{"ok": false, "diagnostics": [{code, severity, message, hint, span}]}`.

## Коди діагностик

| Код | Значення |
|---|---|
| E001 | недопустимий символ |
| E002 | неочікувана лексема (з переліком очікуваних) |
| E003 | несподіваний кінець тексту |
| E004 | зайвий текст після завершення програми |
| E201 | конструкція-розширення в режимі `--strict` |
| E202 | конструкція специфікацій (`→`, виклик функції) у програмі |
| E301 | неправильний формат стану |
| E401 | для циклу не задано інваріант |
| E402 | синтаксична помилка у формулі специфікації |
| E403 | невідома функція або неправильна кількість аргументів |
| E404 | неповна специфікація (немає pre/post/invariant, файлу тощо) |
| E405 | некоректний TOML |
| E406 | анотацій `[[loop]]` більше, ніж циклів |
| E407 | для повної коректності бракує варіанта |
| E901 | помилка читання файлу |
