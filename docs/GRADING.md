# How the score is made

The number is the least interesting part of the report, but it should never be mysterious. This is
the whole rubric: four components, fixed weights, integer out of ten. It runs on your machine in
milliseconds, with no model and no network.

```python
score = round(10 * (0.35*completion + 0.30*alignment + 0.20*coverage + 0.15*focus))
```

Clamped to 1–10. If any component is unknown it counts as 0.5, never as zero: a missing measurement
is not evidence of failure.

## 1. Plan completion — 35%

Did the things you wrote down get any time at all?

Each plan item is worth a weight: **this week's objectives 1.0**, **today's tasks 0.8**, **the
month's goals 0.6** — because a month goal is allowed to be further away. An item scores 1.0 if it
was checked off on the plan or if a check-in carried its hashtag, 0.6 if it was matched only by the
words, and 0 if the log never mentions it.

```
Objectives:   "Write the onboarding copy"      tagged        1.0 × 1.0
              "Finish chapter two"              estimated     0.6 × 1.0
              "Ship the beta"                   untouched     0.0 × 1.0
Month goal:   "Finish the chapter draft"        untouched     0.0 × 0.6
                                                            -----------
                                                            1.6 / 3.6  = 44%
```

That 0.6 is why the report says "untagged estimate" out loud. If you want the credit to be exact,
type the tag.

## 2. Time on plan — 30%

Of the minutes on the record, how many are against something you said mattered?

An entry that matches one objective gets full credit. An entry that matches two splits its minutes
between them. An entry that matches nothing is time on the record that the plan didn't know about —
which is not automatically bad: some of it is the actual job, and the report says so. An estimate
counts at 60% of its minutes so a word match can't outrank a tag.

## 3. Record coverage — 20%

Half of it is your **answer rate** (answers ÷ answers + skips). Half is **day coverage** (days with
any record ÷ days elapsed in the week so far).

This is the component that makes the app care about the misses more than the scrolling. A week you
can read is worth more than a week you can defend.

## 4. Time off the rails — 15%

The share of logged minutes that the small, deliberately obvious distraction lexicon recognised:
social feeds, video, news and rabbit holes, chat and inbox, admin and yak-shaving. It is short on
purpose. A false accusation is worse than a missing one, which is why "newsworthy" is not "news" and
why "wrote a review" is not "reviewed the feed".

Focused time feeds this component up; it is the only one that rewards the shape of the day rather
than its outcome.

## No plan, no score

If the week has no plan, `score` is `None` and the report says there was no standard to grade
against. This is the whole point: the app does not have its own idea of productive. Write a week
whose objective was "rest", spend it resting, and you get a good report.

## Thin records get a caveat, not a high five

A week with 40 minutes on the record and one small objective completed can arithmetically reach 9/10.
The report will say so, and then say: *"40m in 5 days. That's not a week, it's a sample. The score is
a ceiling."* The arithmetic is honest; the prose refuses to oversell it.

## The pattern

The report names exactly one pattern, chosen in this order — and the instruction for next week is
generated from the same choice, so the advice always answers the accusation:

| Pattern | When | What it means |
| --- | --- | --- |
| `kept` | score ≥ 8, at most one objective untouched, coverage ≥ 70 | the list was the right size |
| `unscheduled` | an objective got nothing **and** distractions ≥ 20% of logged time | it was never given a block, so it never competed |
| `invisible` | an objective got nothing, no distraction to blame | it happened, or it didn't, but it never got a line |
| `silence` | 2h+ of unrecorded holes inside your active hours | the week went where you can't see it |
| `drift` | under 60% of logged time matched the plan | the log is full of work the plan didn't know about |
| `steady` | none of the above | no pattern worth naming this week |

## Tone

Gentle, Honest and Brutal read the same numbers, the same pattern and the same score. Only the
sentences change. Gentle is not an easier grade, and Brutal is not a harsher one — it is the same
news with the cushioning removed.

## Changing it

The whole grader is `whatidid/graders/analysis.py`, roughly 250 lines, standard library only. The
weights are a dict at the top. If you think focus should outweigh completion, change four numbers
and run the tests — `tests/test_analysis.py` asserts tone invariance and bounds, not the specific
weights.
