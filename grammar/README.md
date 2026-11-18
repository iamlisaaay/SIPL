# grammar/

Канонічна граматика SIPL – [`src/sipl/grammar/sipl.lark`](../src/sipl/grammar/sipl.lark).
Вона лежить усередині пакета, щоб потрапляти у wheel і завантажуватися через
`importlib.resources`. Копії тут немає, щоб не було двох джерел синтаксису.

* БНФ курсу і пояснення, як знято неоднозначність: [`docs/spec.md`](../docs/spec.md)
* Позитивні приклади: [`tests/data/valid`](../tests/data/valid), [`tests/data/ext`](../tests/data/ext)
* Негативні приклади та очікувані помилки: [`tests/data/invalid`](../tests/data/invalid)

Переглянути граматику з командного рядка:

```bash
python -c "from sipl.parser import grammar_text; print(grammar_text())"
```
