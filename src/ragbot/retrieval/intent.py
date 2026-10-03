"""Rules-based intent classification. Deterministic, auditable, and cheap.

Four intents, and the routing they drive:

- ``FACTUAL`` - answerable from the closed corpus.
- ``OPINION`` - advice-seeking. Routed to Refusal A (educational link). Never
  reaches fact retrieval.
- ``OUT_OF_SCOPE`` - about something the corpus does not cover. Refusal B.
- ``CORPUS_SOURCES`` - "which pages are you using?", "how many funds are you
  referring to?". A question about the corpus itself, or about its extent.
  Answered from ``config/corpus.yaml``, without retrieval, because no retrieved
  chunk describes the corpus and no similarity score can decide it.

Why intent is decided BEFORE retrieval, rather than left to the confidence gate:
these pages are dense with ratios, fund characteristics and risk text, so
"Should I buy HDFC Equity for 5 years?" retrieves *strong* context and would sail
through any similarity threshold. The gate cannot detect an advice request. Only
intent can, and it must not be delegated to a score.

LLM fallback is deliberately NOT implemented. There is no LLM client until Phase 4
and the spec makes rules authoritative ("rules FIRST, LLM fallback only for
phrasings the rules do not match"). Unmatched questions return FACTUAL with
``needs_fallback=True`` so the seam is visible rather than silently wrong; the
Phase 4 output screens remain the actual control on what may be stated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..core.models import Intent

__all__ = [
    "Intent",
    "IntentMatch",
    "classify",
    "explain",
    "is_performance_claim",
    "is_source_list_question",
    "names_corpus_scheme",
    "non_corpus_scheme",
    "NO_RULE_MATCHED",
]

NO_RULE_MATCHED = "default:unmatched"

# --- rule sets -----------------------------------------------------------
#
# Word-boundary anchored throughout. Substring matching is how "invest" ends up
# inside "investor education" and "good" inside "goodbye", producing refusals for
# ordinary factual questions - a failure mode that looks like the assistant is
# broken rather than mis-tuned.

# Phrase-level, not bare-word, where the bare word also occurs in real factual
# questions. Every rule below was checked against the corpus's own vocabulary.
#
# The failures this prevents are not hypothetical. An earlier version of this
# file used bare `exit`, `top`, `allocation` and `worth`, and misrouted six
# legitimate questions:
#
#   "What is the exit load on HDFC Equity Fund?"  -> opinion  (bare `exit`)
#   "What is the asset allocation of HDFC...?"     -> opinion  (bare `allocation`)
#   "What are the top 10 holdings?"                -> opinion  (bare `top`)
#   "Can I redeem after 3 years?"                  -> opinion  (bare `redeem`)
#   "What is the exit load after the lock-in?"     -> opinion  (bare `exit`)
#
# Each would have been refused with an educational link - confidently, and
# wrongly. `exit load` is one of the corpus's core fields, `asset allocation`
# and `top holdings` are disclosed on the pages, and redeeming after a lock-in
# is a stated term. So: no bare word that also names a corpus field.

_OPINION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("should_i", re.compile(r"\bshould\s+(?:i|we|one|anyone|you)\b", re.I)),
    ("advice", re.compile(r"\b(?:advi[sc]e|advisor|guidance)\b", re.I)),
    # `sell` and `purchase` are unambiguous. `exit` and `redeem` are NOT: "exit
    # load" and "redeemed after 3 years" are both corpus facts, so they only
    # count as advice with an object.
    ("buy", re.compile(r"\b(?:buy|purchase)\b", re.I)),
    ("sell", re.compile(r"\b(?:sell|exit\s+(?:the|my|our)|redeem\s+(?:the|my|our))\b", re.I)),
    ("invest_in", re.compile(r"\binvest(?:ing)?\s+in\b", re.I)),
    ("recommend", re.compile(r"\b(?:recommend(?:ed|ation)?|suggest(?:ion)?|advise)\b", re.I)),
    # No bare `top`: these pages have a "Top 10 holdings" table.
    ("superlative", re.compile(r"\b(?:best|better|optimal)\b", re.I)),
    ("worth", re.compile(r"\bworth\s+(?:it|buying|investing|holding|holding\?)\b", re.I)),
    ("good_fund", re.compile(r"\bgood\s+(?:fund|scheme|investment|choice|option)\b", re.I)),
    ("which_is_good", re.compile(r"\bwhich\s+is\s+(?:good|better|best|safe)\b", re.I)),
    # Advice forms only. "What is the asset allocation?" is a disclosed field
    # and must stay factual, so bare `allocation` is excluded.
    ("allocation", re.compile(r"\b(?:allocate\s+(?:my|our|it|to)|rebalanc\w*|diversif\w+)\b", re.I)),
    ("my_portfolio", re.compile(r"\b(?:my|our|his|her|their)\s+portfolio\b", re.I)),
    ("portfolio_build", re.compile(r"\b(?:build|construct|create|start)\s+(?:a|my|an)\s+portfolio\b", re.I)),
    ("switch", re.compile(r"\bswitch\s+(?:to|from|over|out\s+of)\b", re.I)),
)

# A process question about obtaining a statement. Checked FIRST, ahead of both
# the tax rules and the opinion rules, because the corpus does not cover
# "capital gains" as a topic but the source explicitly requires
# "how do I download my capital-gains statement" to be FACTUAL. Without this
# precedence the phrase "capital gains" would route the question to Refusal B
# and the assistant would refuse something it is required to answer.
_STATEMENT_REQUEST = re.compile(
    r"\b(?:how|where|what)\b[^?]{0,40}?"
    r"\b(?:download|get|generate|obtain|request|view|see|find|access)\b[^?]{0,30}?"
    r"\bstatement\b",
    re.I,
)

_OTHER_AMCS = re.compile(
    r"\b(?:sbi|kotak|axis|icici|nippon|bajaj|canara|pnb|idfc|mirae|quant|parag\s+parikh|"
    r"motilal|shriram|tata\s+sl|mahindra\s+mancaps|uti|prINCIPal|dsp|lt\s+mf|"
    r"bandhan|baroda\s+pioneer|jm\s+financial|sundaram|hsbc\s+mf)\b",
    re.I,
)

_TAX = re.compile(
    r"\b(?:itr|income\s+tax|tax\s+(?:return|planning|saving|benefit|harvest|gift)|"
    r"advance\s+tax|section\s*80[cdb]?|80[cdb]\b|capital\s+gains\s+tax|"
    r"tax[- ]free|declaration)\b",
    re.I,
)

_INSURANCE = re.compile(
    r"\b(?:insurance|term\s+plan|life\s+cover|health\s+cover|lic\b|ulip|"
    r"endowment|vehicle\s+cover)\b",
    re.I,
)

_BANKING = re.compile(
    r"\b(?:bank\s+account|savings\s+account|fixed\s+deposit|recurring\s+deposit|"
    r"fd\b|rd\b|emi\b|credit\s+card|net\s+banking|upi\b|cheque|loan|"
    r"mortgage|gold\s+bond)\b",
    re.I,
)

_LEGAL = re.compile(
    r"\b(?:legal\s+notice|lawyer|attorney|court|litigation|consumer\s+forum|"
    r"sebi\s+complaint|legal\s+advice)\b",
    re.I,
)

# Split from `other_amc` deliberately - see `explain` for why the ordering of
# these two groups relative to the opinion rules is not arbitrary.
_DOMAIN_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("tax", _TAX),
    ("insurance", _INSURANCE),
    ("banking", _BANKING),
    ("legal", _LEGAL),
)

_OTHER_AMC_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (("other_amc", _OTHER_AMCS),)


# --- non-corpus schemes of OUR OWN AMC -----------------------------------
#
# The spec's out_of_scope list is "other AMCs, non-corpus schemes, tax planning,
# legal, insurance, banking". The other-amc half was implemented and this half was
# not, which is invisible until a question names a real scheme of our own AMC that
# we do not hold. It then sails through: `corpus_scheme` matches on `\bhdfc\b`, so
# ANY HDFC fund is treated as in-corpus.
#
# Phase 6 measured the cost, and it is not small. "What is the expense ratio of
# the HDFC Mid Cap Fund?" scored `raw_dense_max=0.8541` - above four of the five
# real factual questions in the set - because all five corpus pages are HDFC
# Direct-Growth scheme pages with near-identical structure, so a mid-cap question
# retrieves Large Cap's expense-ratio row almost perfectly. The correct answer and
# the out-of-corpus question are, to a similarity threshold, the same question.
#
# This is precisely the failure the gate cannot prevent: it is not a scoring
# problem, it is a scope decision, and scope is what the router is for.
#
# The check is against the corpus itself, not a hardcoded list, so adding a sixth
# scheme to `config/corpus.yaml` extends scope automatically.
#
# It fires only when the named phrase contains the AMC token. That narrowness is
# the whole safety margin: "What is a mutual fund?" contains the phrase "mutual
# fund" but no AMC, so generic vocabulary is never mistaken for a scheme name.

#: A Capitalised phrase ending in "Fund" - the shape every scheme name is written
#: in. Capitalisation is load-bearing, not cosmetic: a looser shape also matches
#: the run of ordinary words before it, and "the expense ratio of HDFC Large Cap
#: Fund" then yields the phrase "ratio of HDFC Large Cap Fund", whose `ratio` is
#: not a corpus token - so the one question the rule must never touch gets
#: refused. Measured, not assumed: that is what the first version did.
_SCHEME_NAME = re.compile(r"\b((?:[A-Z][A-Za-z0-9&.\-]*\s+){1,4}Fund)\b")

#: Lowercase fallback, anchored on the AMC so it cannot swallow question words.
#: Only reachable for an all-lowercase question, where capitalisation carries no
#: information ("expense ratio of hdfc mid cap fund").
_SCHEME_NAME_LOWER = re.compile(r"\bhdfc((?:\s+[a-z0-9&.\-]+){1,4}\s+fund)\b")

#: ETF-shaped names: the AMC, a bounded run, then "ETF".
#:
#: This exists because the shape above ENDS IN "Fund", and every one of the five
#: corpus schemes does, so the rule could not see an exchange-traded fund at all.
#: `non_corpus_scheme` therefore never fired for one, it routed FACTUAL, and the
#: confidence gate had to refuse it on a cosine. Measured, and it was one rounding
#: error away from a false answer: "list the scheme details of the HDFC Nifty 50
#: ETF" scores `raw_dense_max=0.7563` against the calibrated 0.7562.
#:
#: ALL SIX calibration probes (P1-P6) are ETF questions, so they reached the gate
#: for this reason alone - and the gate was the only thing refusing them. Closing
#: the gap therefore leaves `calibrate.choose()` with no gate-routed negative and
#: it refuses to write a number ("a one-sided threshold is not a boundary"), which
#: is correct behaviour and not a crash. The committed 0.7562 in
#: `artifacts/calibration.json` is unaffected at runtime, and no honest negative
#: class can replace the probes: every genuinely out-of-corpus HDFC product is now
#: correctly router-refused, so the probes were only ever measuring the gate
#: because the router was blind. Rebuilding that class is a decision about the
#: calibration, and belongs in one - not in a routing fix.
#:
#: That is the failure `non_corpus_scheme` was written to prevent and could not:
#: it is a SCOPE decision, not a scoring one. An ETF is a different product class
#: from a mutual fund - different NAV, different charges, no SIP, no exit load, no
#: lock-in - so no chunk of these five pages answers a question about one, however
#: well the text happens to overlap. Routing is the instrument that can say so.
#:
#: Anchored on the literal AMC token rather than on capitalisation, for the reason
#: the pattern above is not: a capitalised run can start on an ordinary word, and
#: the run has to stay contiguous from the AMC to be a NAME. `HDFC` cannot be an
#: ordinary word, so anchoring here removes that failure mode instead of
#: constraining around it, and it is why no separate lowercase fallback is needed -
#: `re.I` covers "hdfc nifty 50 etf" as well.
#:
#: Width 5, not 3. The run is contiguous from the AMC, so a wider window is not a
#: wildcard; 5 is the longest real name in the corpus's own probe set ("HDFC
#: Banking and Financial Services ETF", four intervening tokens), and a capitalised
#: run of that length would stop at the lowercase "and" and miss it.
#:
#: "etf" is deliberately NOT in `_NOT_DISTINCTIVE`. It is the token that makes the
#: name non-corpus, and stripping it would leave `{nifty, 50}`, which a scheme
#: named after an index could match.
_ETF_NAME = re.compile(r"\b(hdfc(?:\s+[a-z0-9&.\-]+){0,5}\s+etfs?)\b", re.I)

#: Tokens that carry no scheme identity. "HDFC Large Cap Fund" and
#: "HDFC Equity Fund" differ only in their distinctive tokens, so these are
#: stripped before the comparison.
_NOT_DISTINCTIVE = frozenset(
    {"hdfc", "fund", "direct", "growth", "plan", "option", "variant", "the",
     "a", "an", "of", "and", "savings", "tax", "saver", "dividend"}
)


@lru_cache(maxsize=1)
def _corpus_scheme_tokens() -> frozenset[str]:
    """Every word appearing in any corpus scheme name, lowercased.

    Read from `config/corpus.yaml` rather than duplicated here. A hardcoded copy
    would drift the moment a scheme is added, and a scope rule that silently stops
    matching the corpus is worse than no rule: it would start refusing real
    questions while looking correct.
    """
    try:
        from ..core.config import load_corpus

        pages = load_corpus()["pages"]
    except Exception:  # noqa: BLE001 - routing must not depend on config loading
        return frozenset()
    tokens: set[str] = set()
    for page in pages:
        for word in re.split(r"[^A-Za-z0-9]+", str(page.get("scheme", ""))):
            if word:
                tokens.add(word.lower())
    return frozenset(tokens)


def non_corpus_scheme(question: str) -> bool:
    """Does the question name an HDFC scheme that is not one of the five?

    True means out of scope. Requires three things at once, and the AND is the
    design: a scheme-shaped phrase, the AMC token inside it, and a distinctive
    token set that no corpus scheme covers. Dropping any one of them widens the
    rule into territory where it would refuse legitimate questions.
    """
    corpus = _corpus_scheme_tokens()
    if not corpus:
        return False
    for phrase in _scheme_candidates(question):
        words = [w.lower() for w in re.split(r"[^A-Za-z0-9]+", phrase) if w]
        if "hdfc" not in words:
            continue  # not our AMC - `other_amc` owns that case
        distinctive = {w for w in words if w not in _NOT_DISTINCTIVE}
        if distinctive and not distinctive.issubset(corpus):
            return True
    return False


def _scheme_candidates(question: str) -> list[str]:
    """Every scheme-shaped phrase in the question, in either capitalisation style.

    Split out of `non_corpus_scheme` so the scope rule and the source-list rule
    below read the SAME phrases. Two rules that each grew their own extractor
    would disagree on the questions where they overlap, and the overlap is
    exactly where a safeguard silently stops applying.

    The ETF shape is a third extractor for the same reason, and it is listed
    here rather than inside `non_corpus_scheme` because `names_corpus_scheme`
    must see it too: a name ending in "ETF" is never a corpus scheme, so leaving
    it out of the shared list would let the source-list rule reason about a
    question containing one without the name in hand.
    """
    candidates = [m.group(0) for m in _SCHEME_NAME.finditer(question)]
    candidates += ["hdfc" + m.group(1) for m in _SCHEME_NAME_LOWER.finditer(question)]
    candidates += [m.group(1) for m in _ETF_NAME.finditer(question)]
    return candidates


def names_corpus_scheme(question: str) -> bool:
    """Does the question name ONE specific scheme that the corpus does hold?

    The mirror image of `non_corpus_scheme`, and the guard that keeps the
    source-list rule from eating ordinary questions. "What do you know about
    HDFC Large Cap Fund?" contains both a self-reference and a scheme name, and
    it is a question ABOUT that fund - it must go to retrieval, not be answered
    with the page list. So: a scheme name present means the question is about
    that scheme, and the list is not what was asked for.
    """
    corpus = _corpus_scheme_tokens()
    if not corpus:
        return False
    for phrase in _scheme_candidates(question):
        words = [w.lower() for w in re.split(r"[^A-Za-z0-9]+", phrase) if w]
        if "hdfc" not in words:
            continue
        distinctive = {w for w in words if w not in _NOT_DISTINCTIVE}
        # An empty distinctive set is "HDFC Fund" - the AMC and the noun, with
        # nothing identifying. That is not a scheme name, and treating it as one
        # would block the source-list rule on every question of this shape.
        if distinctive and distinctive.issubset(corpus):
            return True
    return False


# --- the corpus source list -----------------------------------------------
#
# "name the hdfc fund pages that you are using" is a question about the corpus
# itself, and it was being refused. Traced end to end: it classified `factual`,
# retrieved, and the gate closed at `raw_dense_max=0.7540` against the calibrated
# threshold of 0.7562 - a two-thousandth of a cosine, decided by nothing more
# meaningful than which fund page happened to sit nearest. Measured: -0.0000
# below the bar. The chunks it retrieved were HDFC Equity's "Fund house"
# boilerplate (website, camsonline), which contains nothing about which pages
# the assistant covers, so no threshold could have produced the right answer and
# no prompt could have either.
#
# Retrieval is the wrong instrument for a question about the corpus. The answer
# is the corpus definition itself, so it is read from `config/corpus.yaml` and
# the five names are never generated, ranked or summarised by a model.
#
# Three conditions, and all three are required:
#
# 1. A self-reference next to a corpus noun - "pages you are using", "sources
#    do you use", "your corpus". `you` alone is far too loose: "What do you know
#    about HDFC Large Cap Fund?" matches it, and that is a question about a fund.
#    TWO phrasings of the same question have no pronoun at all - "How many mutual
#    funds of HDFC are you referring?" and "What schemes are covered?" - so two
#    further branches match on the interrogative instead, and `_FACTUAL_FIELD`
#    below is what makes the substitution safe. The corpus noun stays PLURAL in
#    all four, which is what keeps the singular cases out.
# 2. No corpus field named in the question. See `_FACTUAL_FIELD` below.
# 3. No corpus scheme named in the question, which is what rules out "What do you
#    know about HDFC Large Cap Fund?".

_SOURCE_SELF = (
    r"(?:you|your|yours|yourself|"
    r"this\s+(?:assistant|app|application|bot|chatbot|system|tool)|"
    r"the\s+assistant)"
)
#: PLURAL, deliberately. A question about which pages the corpus holds asks for a
#: list, and the corpus is five pages. The singular is what makes "the NAV of
#: YOUR fund" match: "your fund" there means the reader's own fund, which is an
#: ordinary performance-claim question and must reach retrieval and the output
#: screen, not get a page list. Every phrasing this rule must catch is plural or
#: the word "corpus".
_SOURCE_NOUN = r"(?:pages|sources|corpus|documents|schemes|funds)"
#: Gerunds and the reference verbs are here because a question about the corpus's
#: extent is often phrased mid-sentence: "which mutual funds of HDFC are you
#: referring to" ends in a participle, not in one of the bare stems. A verb list
#: of only base forms reads as complete and silently misses half the family.
_SOURCE_VERB = (
    r"(?:use|uses|used|using|cover|covers|covered|covering|have|has|had|"
    r"include|includes|included|including|read|reads|reading|draw|draws|drawn|"
    r"trained|answer|answers|answering|base|based|hold|holds|"
    r"know|knows|known|"
    r"contain|contains|contained|list|lists|listed|name|names|named|"
    r"refer|refers|referred|referring|referenced|mean|means|meant|meaning|"
    r"support|supports|supported|available)"
)
#: Coverage verbs only, for the branch that has no `you` to lean on. Narrower
#: than `_SOURCE_VERB` on purpose: without the self-reference anchor these verbs
#: are the only thing distinguishing "what schemes are covered" from "what schemes
#: should I pick". The ambiguous ones - `have`, `hold`, `answer` - are left out,
#: so dropping the anchor costs coverage rather than precision.
_EXTENT_VERB = (
    r"(?:use|uses|used|using|cover|covers|covered|covering|"
    r"include|includes|included|including|contain|contains|contained|"
    r"list|lists|listed|name|names|named|known|read|reads|reading|"
    r"support|supports|supported|available|offer|offers|offered)"
)
#: "your holdings" and "the fund manager" are questions about holdings or a
#: manager, not about which pages exist - the same distinction `_OPINION_RULES`
#: draws when it refuses `my portfolio` instead of answering it.
_SOURCE_NOT_ABOUT = r"(?!\s+(?:holding|holdings|manager|managers)\b)"

_SOURCE_LIST = re.compile(
    rf"\b(?:"
    # noun ... self ... verb: "the pages you are using", "sources do you use"
    rf"{_SOURCE_NOUN}{_SOURCE_NOT_ABOUT}[^?]{{0,30}}?\b{_SOURCE_SELF}\b"
    rf"[^?]{{0,20}}?\b{_SOURCE_VERB}\b"
    rf"|"
    # self ... noun: "your corpus", "this assistant's source pages"
    rf"\b{_SOURCE_SELF}\b[^?]{{0,25}}?\b{_SOURCE_NOUN}{_SOURCE_NOT_ABOUT}\b"
    rf"|"
    # quantity: "how many mutual funds of HDFC are you referring?"
    rf"how\s+many\b[^?]{{0,40}}?\b{_SOURCE_NOUN}{_SOURCE_NOT_ABOUT}\b"
    rf"|"
    # extent with no self-reference: "what schemes are covered?"
    rf"\b(?:what|which)\b[^?]{{0,30}}?\b{_SOURCE_NOUN}{_SOURCE_NOT_ABOUT}\b"
    rf"[^?]{{0,30}}?\b{_EXTENT_VERB}\b"
    rf")",
    re.I,
)

# --- the veto that pays for dropping the self-reference ------------------
#
# Branches C and D above match a corpus noun with no `you` in the question, and
# that anchor was the reason the first two branches were safe. "What schemes are
# covered?" has no pronoun at all - it is about the corpus, plainly - and there
# was no way to say so without also matching "What schemes should I pick?".
#
# So the two things a corpus-extent question never has are enforced explicitly:
# it names no field of a fund, and it names no particular scheme. The second is
# `names_corpus_scheme`; the first is this.
#
# The field check is what makes the new branches safe, and it is a question about
# the asker rather than the askee. "What are the expense ratios of the funds you
# cover?" is a question about five expense ratios, and handing back the page list
# would answer a different question than the one asked - silently, confidently,
# and with a citation-shaped answer nobody can check. Naming a field is the
# signal that the question is about a fund, whatever else it says.
_FACTUAL_FIELD = re.compile(
    r"\b(?:expenses?|ratios?|exit\s+loads?|loads|charges?|fees?|"
    r"sip|systematic\s+investment|minimum|mins?|lock[\s-]?in|"
    r"benchmarks?|indices|index|riskometer|risks?|nav|unit\s+price|"
    r"statements?|aum|asset\s+allocation|allocations?|"
    r"holdings?|managers?|management|"
    r"performance|returns?|cagr|yield|volatility|ratings?|"
    r"portfolios?|categories|eligibility|suitab\w+)\b",
    re.I,
)
#: Three things are absent from `_FACTUAL_FIELD` on purpose, and each omission is
#: a question this rule would otherwise leave refused:
#:
#: - `hdfc` - the AMC token. "How many mutual funds of HDFC are you referring?"
#:   asks about the corpus's extent while naming the AMC, which is the whole
#:   reported query. A field list containing it vetoes the very question the rule
#:   exists to answer.
#: - `direct` / `growth` - plan vocabulary, not a field. "How many HDFC Direct
#:   Growth funds do you cover?" is a corpus-extent question, and the suffix is on
#:   all five entries in `corpus.yaml`.
#: - `tax` - "How many tax-saving funds do you cover?" is a corpus-extent
#:   question and ELSS is one of the five. Genuine tax questions are claimed
#:   earlier by `_TAX`, which outranks this rule, so nothing is lost by the gap.


def is_source_list_question(question: str) -> bool:
    """Is this a question about which pages THIS assistant covers?

    Three conditions, all required - see the comments above `_SOURCE_LIST` and
    `_FACTUAL_FIELD`. The order is cheapest-first but the last two are
    interchangeable; what is not interchangeable is dropping any of them, which
    is the over-refusal this rule was written to stop.
    """
    q = _norm(question)
    if not q or not _SOURCE_LIST.search(q):
        return False
    if _FACTUAL_FIELD.search(q):
        return False
    return not names_corpus_scheme(q)


# --- generic scheme-detail asks -----------------------------------------
#
# "List the scheme details of HDFC ELSS" is a question about a scheme the corpus
# holds, so it belongs in front of retrieval. It used to get there BY ACCIDENT:
# the AMC backstop `corpus_scheme` matches the bare token `\bhdfc\b`, so any
# question mentioning the AMC was factual whether or not these rules understood
# it. Take the AMC away and the identical question fell through to
# `default:unmatched` - still FACTUAL, but flagged `needs_fallback`, so the CLI
# reported a missing rule rather than the rule that actually applied.
#
# The rule below closes that gap. Its authority is provably small, and the proof
# is the position, not a comment: `_FACTUAL_RULES` is the LAST step of
# `explain()`, after the domain, opinion, other-AMC, non-corpus-scheme and
# source-list checks. Every query that reaches it was already going to be
# answered FACTUAL by the fallback on the very next line. So matching here cannot
# convert a refusal into an answer, an answer into a refusal, or a corpus source
# list into a retrieval. It changes `rule` and clears `needs_fallback` - and
# those two are consumed only by the CLI, the calibration report and the refusal
# `cause` string, none of which branch on them.
#
# `details` is never matched bare, for the same reason `exit load` is not matched
# as `exit`. "Details" is generic English, not corpus vocabulary, and the phrases
# it appears in run the whole range: "give me the details on my portfolio" is
# advice, "details about the fixed deposit rate" is a domain the corpus has
# nothing on, and "details about the funds you cover" is a question about the
# corpus. All three are claimed correctly today - but by rules that happen to sit
# EARLIER, and a safeguard that only holds because of another rule's position is
# not a safeguard. So the pattern requires a scheme-shaped noun on one side of
# `details` / `about`, which is the thing that makes it a question about a scheme
# rather than a question about a portfolio, a deposit or the corpus itself.
#
# Deliberately NOT added to `_FACTUAL_FIELD`. That regex is the veto inside
# `is_source_list_question`, and adding `scheme details` to it would turn "list
# the scheme details of the funds you cover" - a corpus-extent question, answered
# correctly from `corpus.yaml` today - into a retrieval. The two rules are
# different questions and must not share a vocabulary entry.

#: A scheme-shaped noun. `elss` is listed separately because it is a corpus
#: category written as an acronym and never carries the word "fund" - "ELSS
#: details" and "details about the ELSS" both name a scheme the corpus holds.
_SCHEME_NOUN = r"(?:mutual\s+funds?|schemes?|funds?|elss)"

_SCHEME_DETAIL_ASK = re.compile(
    # "scheme details", "fund detail", "key details of HDFC ELSS"
    rf"\b{_SCHEME_NOUN}\s+(?:basic\s+|key\s+|main\s+|full\s+|complete\s+)*details?\b"
    # "details about the ELSS", "information on HDFC Large Cap Fund"
    rf"|\b(?:details?|information|info|overview|summary)\s+(?:about|on|of|for)\s+"
    # Optional determiner, optional AMC, then a BOUNDED run of at most three
    # intervening tokens before the scheme noun. Bounded, because the corpus's
    # own names are multi-word - "HDFC Large Cap Fund", "HDFC Balanced Advantage
    # Fund" - and a one-token window left the rule matching only the two-token
    # names. Three is the width of the names, not a wildcard: the run has to be
    # CONTIGUOUS from the determiner, so "the top ten holdings across every
    # equity fund I hold" still fails, because `across` breaks the run before
    # `fund` is reachable.
    rf"(?:the\s+|this\s+|that\s+|these\s+|those\s+|an?\s+)?"
    rf"(?:hdfc\s+)?(?:[A-Za-z0-9&.\-]+\s+){{0,3}}{_SCHEME_NOUN}\b",
    re.I,
)


_FACTUAL_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("expense_ratio", re.compile(r"\bexpense\s+ratio\b", re.I)),
    ("exit_load", re.compile(r"\bexit\s+load\b", re.I)),
    ("sip", re.compile(r"\b(?:sip|systematic\s+investment)\b", re.I)),
    ("minimum", re.compile(r"\bmin(?:imum|\.)?\b", re.I)),
    ("lock_in", re.compile(r"\block[\s-]?in\b", re.I)),
    ("benchmark", re.compile(r"\bbenchmark\b", re.I)),
    ("riskometer", re.compile(r"\brisk(?:ometer)?\b", re.I)),
    ("nav_statement", re.compile(r"\b(?:nav|statement)\b", re.I)),
    ("aum", re.compile(r"\baum\b", re.I)),
    ("asset_allocation", re.compile(r"\basset\s+allocation\b", re.I)),
    ("holdings", re.compile(r"\bholdings?\b", re.I)),
    ("fund_manager", re.compile(r"\bfund\s+manager\b", re.I)),
    ("direct_growth", re.compile(r"\b(?:direct|growth)\s+(?:plan|option|variant)?\b", re.I)),
    # After every specific field above, so a question that names one reports that
    # field rather than the broad ask - "the exit load and the scheme details"
    # is an exit-load question that also wants a summary. Before `corpus_scheme`
    # below, so a scheme-detail query reports itself instead of the AMC token it
    # happens to contain, which is the difference between a rule that understood
    # the question and one that noticed a word in it.
    ("scheme_details", _SCHEME_DETAIL_ASK),
    ("corpus_scheme", re.compile(r"\bhdfc\b", re.I)),
    ("reasons_to_invest", re.compile(r"\bwhy\s+(?:should|to)\b", re.I)),
)

# --- performance-claim detection ----------------------------------------
#
# Separate from intent ON PURPOSE. A request for the current NAV price is a
# performance claim, but it is still a question ABOUT the corpus, so its intent
# is FACTUAL and it should go to retrieval. What forbids answering it is the
# output performance screen in Phase 4 (FR-20), not the router. Folding this
# into intent would make the router a second, weaker output screen, and would
# leave the mandated one untested.

# The performance screen's vocabulary, per the Phase 4 spec: "return/returns/CAGR/
# yield, period figures ('1-year', '3-year'), and return-shaped numbers".
#
# `return`/`cagr`/`yield` are matched UNCONDITIONALLY. An earlier version required
# an adjacent period figure to fire, so "What is the CAGR?" passed the screen and
# a CAGR - the most concentrated form of a return - would have been stated. Asking
# for a return is a request to state one, period or no period.
#
# `performance` is the exception, because "performance risk" and "performance
# score" are riskometer vocabulary: refusing those would block a legitimate
# factual question.
_PERF_WORDS = re.compile(
    r"\b(?:return(?:s|ed)?|cagr|yield|perform(?:s|ed|ing)?)\b"
    r"|\bperformance\b(?!\s*(?:risk|score|rating|ratio|volatility))",
    re.I,
)
_PERF_PERIOD = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*(?:year|yr|month)s?|since\s+inception|1\s*yr|3\s*yr|5\s*yr)\b",
    re.I,
)
# "18% in 3 years", "12.5% p.a." - a percentage with a period attached to it.
# Period-attached percentages are return-shaped even when the word "return" is
# absent, which is why this is checked independently of _PERF_WORDS.
_PERF_SHAPED_NUMBER = re.compile(
    r"\d+(?:\.\d+)?\s*%[^.]{0,20}?(?:\b(?:in|over|pa|p\.?a\.?|annuali[sz]ed)\b|\b\d+\s*(?:year|yr))",
    re.I,
)
_PERF_NAV_PRICE = re.compile(
    r"\b(?:nav|unit\s+price|price\s+per\s+unit|market\s+price)\b"
    r"[^?]{0,30}?\b(?:today|current|now|what|is|of|latest|value|price)\b",
    re.I,
)
_PERF_RANKING = re.compile(
    r"\b(?:best|top|highest|lowest)\s+(?:performing|performer|return|gainer)\b", re.I
)

# Fee vocabulary. A question framed around a fee is a fee question even when it
# mentions a period: "exit load after 3 years" asks about a charge, not a return.
_FEE_CONTEXT = re.compile(
    r"\b(?:expense\s+ratio|exit\s+load|lock[\s-]?in|minimum|sip|benchmark|"
    r"riskometer|aum|holding|charge|fee)\b",
    re.I,
)


def _norm(question: str) -> str:
    return re.sub(r"\s+", " ", question).strip()


def _first_match(
    question: str, rules: tuple[tuple[str, re.Pattern[str]], ...]
) -> str | None:
    for name, pattern in rules:
        if pattern.search(question):
            return name
    return None


@dataclass(frozen=True)
class IntentMatch:
    """A classification plus the rule that produced it.

    `rule` is carried so a wrong routing is debuggable from the CLI output alone,
    and so Phase 6 can report which rules actually fire across the golden set
    instead of only measuring end-to-end accuracy.
    """

    intent: Intent
    rule: str
    needs_fallback: bool = False

    @property
    def is_factual(self) -> bool:
        return self.intent is Intent.FACTUAL


def explain(question: str) -> IntentMatch:
    """Classify and report which rule decided it."""
    q = _norm(question)
    if not q:
        return IntentMatch(Intent.OUT_OF_SCOPE, "empty", needs_fallback=True)

    # 1. Statement requests win outright. See the comment on _STATEMENT_REQUEST.
    if _STATEMENT_REQUEST.search(q):
        return IntentMatch(Intent.FACTUAL, "statement_request")

    # 2. Domains the assistant has NOTHING on, checked BEFORE opinion.
    #    "Which bank offers the best FD rate?" contains "best", so the opinion
    #    rules would claim it - but the answer is not "you're asking for advice,
    #    here is an article about mutual funds". It is "we cover HDFC mutual fund
    #    pages only". Refusal A's educational link is on-topic for a mutual-fund
    #    question and a non-sequitur for a bank deposit, so domain beats intent.
    domain = _first_match(q, _DOMAIN_RULES)
    if domain:
        return IntentMatch(Intent.OUT_OF_SCOPE, domain)

    # 3. Opinion, ahead of the other-AMC check. "Should I buy Kotak Flexi Cap?"
    #    is a request for advice about a MUTUAL FUND, so mutual-fund education is
    #    relevant and Refusal A is the better answer. It is also the case the
    #    source cares most about never being answered, so it is not demoted
    #    behind a scope check.
    opinion = _first_match(q, _OPINION_RULES)
    if opinion:
        return IntentMatch(Intent.OPINION, opinion)

    # 4. A scheme from another AMC: nothing to retrieve, no advice refused.
    amc = _first_match(q, _OTHER_AMC_RULES)
    if amc:
        return IntentMatch(Intent.OUT_OF_SCOPE, amc)

    # 4b. A scheme from OUR OWN AMC that is not in the corpus. Ahead of the
    #     factual rules, because `corpus_scheme` matches on `\bhdfc\b` and would
    #     otherwise route it factual - sending a question about a fund we do not
    #     hold into retrieval, where it matches our five near-identical HDFC pages
    #     strongly and confidently. See `non_corpus_scheme` for the measurement.
    if non_corpus_scheme(q):
        return IntentMatch(Intent.OUT_OF_SCOPE, "non_corpus_scheme")

    # 4c. "which pages do you cover" - a question about the corpus itself.
    #     Placed HERE, after every scope check and after opinion, on purpose:
    #     the new rule is the only one that can turn a refusal into an answer,
    #     so it must be the last word to be heard, never the first. "Should I buy
    #     HDFC Equity?" is still an advice refusal, and "Do you cover the HDFC
    #     Mid Cap Fund?" is still out of scope - the scope check above has
    #     already claimed both by the time this runs.
    if is_source_list_question(q):
        return IntentMatch(Intent.CORPUS_SOURCES, "corpus_source_list")

    # 5. Recognised factual vocabulary.
    factual = _first_match(q, _FACTUAL_RULES)
    if factual:
        return IntentMatch(Intent.FACTUAL, factual)

    # 5. Unmatched. Default to FACTUAL rather than OUT_OF_SCOPE: the confidence
    #    gate and the Phase 4 output screens are the mechanisms that decide
    #    answerability, and defaulting to OUT_OF_SCOPE would refuse every
    #    phrasing this file failed to enumerate - the worst possible failure
    #    mode, because it looks like a broken assistant rather than a missing
    #    regex.
    return IntentMatch(Intent.FACTUAL, NO_RULE_MATCHED, needs_fallback=True)


def classify(question: str) -> Intent:
    """Rules-first intent classification. See module docstring."""
    return explain(question).intent


def is_performance_claim(question: str) -> bool:
    """Does answering this question require stating a return figure?

    Consumed by the Phase 4 output screen. The rule deliberately does NOT
    blanket-block percentages: an expense ratio is a percentage but is a FEE, and
    blocking all percentages would refuse the single most common factual
    question the corpus can answer.
    """
    q = _norm(question)
    if not q:
        return False
    if _PERF_SHAPED_NUMBER.search(q) or _PERF_RANKING.search(q):
        return True
    if _PERF_NAV_PRICE.search(q):
        return True
    # A period figure on its own ("over 3 years") is a return question; a fee
    # question about the same span ("exit load after 3 years") is not, which is
    # why the fee vocabulary is checked first.
    if _PERF_PERIOD.search(q) and not _FEE_CONTEXT.search(q):
        return True
    return bool(_PERF_WORDS.search(q))
