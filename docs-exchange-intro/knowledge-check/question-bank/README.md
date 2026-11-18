# Question Bank

All knowledge-check and quiz questions for *How a Financial Exchange Works*, in one
place, plus a generator that builds a quiz and its answer key on demand.

| File | Contents |
|---|---|
| `questions.json` | Every question (410) with its five statements, area, difficulty, calculation flag and source. No answers. |
| `answers.json` | Correct/incorrect for every statement, explanations and notes. **Kept encrypted** as `answers.json.gpg`. |
| `questions.schema.json`, `answers.schema.json` | JSON Schemas (2020-12) for the two files. |
| `quizgen.py` | Quiz and answer-key generator (Python 3, standard library only). |
| `extract_from_markdown.py` | One-time migration that built the JSON from the old Markdown quizzes. |

## Generating a quiz

Decrypt the answers first (from `../quiz-20-questions`):

```bash
make decrypt-answers
```

Then, from this directory:

```bash
./quizgen.py --list-areas
./quizgen.py --count 20 --difficulty Medium,Hard --numerical exclude \
    --source both --area implied-orders,auctions-sessions --seed 42 --output midterm.md
```

Negative filters combine with the positive ones, for example:

```bash
./quizgen.py --numerical exclude                   # all difficulties, no calculations
./quizgen.py --exclude-area implied-orders         # every area except implied orders
./quizgen.py --exclude-difficulty Hard --source quiz
```

The `--output midterm.md` example writes `midterm.md` (hand this out) and
`midterm-answer-key.md` (instructor only). Options:

| Option | Meaning | Default |
|---|---|---|
| `--count N` | number of questions | 20 |
| `--difficulty` | comma-separated: `Easy`, `Medium`, `Hard` | all |
| `--numerical` | calculation questions: `include`, `exclude` or `only` | `include` |
| `--source` | `quiz`, `knowledge_check` or `both` | `both` |
| `--area` | comma-separated area ids (see `--list-areas`) | all |
| `--exclude-area` | comma-separated area ids to leave out | none |
| `--exclude-difficulty` | comma-separated difficulty levels to leave out | none |
| `--seed` | random seed; the key records it so the same quiz can be regenerated | random |
| `--title` | title printed on quiz and key | Exchange Concepts Knowledge Check |
| `--output` | quiz file; the key goes next to it as `<name>-answer-key.md` | `quiz.md` |

Questions are picked at random, printed in book order (by area), and each
question's statements are shuffled, so the same question gets different letters
in different quizzes. The conventions box for implied orders is added
automatically when such a question is picked. The key lists every question's
bank id, area and difficulty, the maximum and pass score (70%, rounded down), and
explanations where the bank has them.

Encrypt the answers again when done (`make encrypt-answers`) and never commit
the plaintext `answers.json` (it is git-ignored).

## Editing the bank

Edit `questions.json` and `answers.json` directly. Ids are `KC-vv-nn`
(self-study knowledge checks) or `QZ-vv-nn` (course quizzes); statement ids add
`-1` … `-5`. Notes refer to statements by placeholder, e.g. `{KC-01-06-2}`,
never by letter. Run the tests after editing:

```bash
poetry run pytest docs-exchange-intro/knowledge-check/question-bank/tests --no-cov
```
