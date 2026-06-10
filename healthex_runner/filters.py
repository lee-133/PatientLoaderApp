# Composable filters over PatientSummary objects
#
# Each filter is a small function that returns a predicate
# (a function that takes a PatientSummary and returns True/False)
# They're combined with AND, so a patient must pass every selected filter to match
#
# The point of this shape: adding a new filter
# is a single new function here
# nothing else in the codebase changes
#
# Scope: complexity tier, specific condition match, active-condition count
# range, and demographics (age range, gender, language, state)


from __future__ import annotations
from typing import Callable, Iterable, Optional
from .extract import PatientSummary

Predicate = Callable[[PatientSummary], bool]


# Clinical complexity tier
# Match in any of the given tier keys (see tiers.TIERS)
def by_tier(*tiers: str) -> Predicate:
    """."""
    wanted = {t.strip().lower() for t in tiers if t}
    return lambda p: p.tier in wanted


# Patient active conditions
# Match whose active conditions contain the given term(s)
def has_condition(*terms: str, match_all: bool = False) -> Predicate:

    needles = [t.strip().lower() for t in terms if t.strip()]

    def pred(p: PatientSummary) -> bool:
        haystack = [c.lower() for c in p.active_conditions]
        checks = (any(n in c for c in haystack) for n in needles)
        return (
            all(checks) if match_all else any(n in c for n in needles for c in haystack)
        )

    return pred


# Condition Count
# Match whose active-condition count is within [min, max]
def condition_count_between(
    minimum: Optional[int] = None, maximum: Optional[int] = None
) -> Predicate:

    def pred(p: PatientSummary) -> bool:
        n = p.active_condition_count
        if minimum is not None and n < minimum:
            return False
        if maximum is not None and n > maximum:
            return False
        return True

    return pred


# Patient demographics
# Whose age is within [min, max]
def age_between(
    minimum: Optional[int] = None, maximum: Optional[int] = None
) -> Predicate:

    def pred(p: PatientSummary) -> bool:
        if p.age is None:
            return False
        if minimum is not None and p.age < minimum:
            return False
        if maximum is not None and p.age > maximum:
            return False
        return True

    return pred


# Patient gender
# Matched by gender (e.g. "male", "female")
def by_gender(*genders: str) -> Predicate:
    """."""
    wanted = {g.strip().lower() for g in genders if g}
    return lambda p: (p.gender or "").lower() in wanted


# Patient language
# Matched by language code (e.g. "en", "es")
def by_language(*languages: str) -> Predicate:
    wanted = {l.strip().lower() for l in languages if l}
    return lambda p: (p.language or "").lower() in wanted


# Patient state
# Matched by address state (e.g. "Texas")
def by_state(*states: str) -> Predicate:
    wanted = {s.strip().lower() for s in states if s}
    return lambda p: (p.state or "").lower() in wanted


# Combine data matching all predicates
# No predicates = all
def apply(
    patients: Iterable[PatientSummary], predicates: Iterable[Predicate]
) -> list[PatientSummary]:
    preds = list(predicates)
    return [p for p in patients if all(pred(p) for pred in preds)]
