"""ADR-019's cluster rule: base clusters, splitting, each link kind and its receiving cluster,
the merge limit and context, singletons, the precedence clause, and group numbering."""

from bidwright.clusters import build_clusters, precedence_passages
from bidwright.config import ClusterLimits
from bidwright.graph.consolidate import cluster_task
from bidwright.schemas import ControlRegister, DocumentEntry, Passage, Requirement

LIMITS = ClusterLimits(max_members=12, max_context=8, duplicate_jaccard=0.6)
WORDS = (
    "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november"
    " oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu"
).split()


def _document(doc_id: str, role: str, title: str, file: str, precedence: int) -> DocumentEntry:
    return DocumentEntry.model_validate(
        {
            "doc_id": doc_id,
            "file": file,
            "sha256": "0" * 64,
            "format": "pdf",
            "role": role,
            "title": title,
            "precedence": precedence,
            "pages": 1,
            "sanitized": False,
            "parser": "pdfplumber",
        }
    )


REGISTER = ControlRegister(
    package="pkg",
    precedence_source="rules",
    documents=[
        _document("add", "addendum", "Addendum 1", "addendum_1.pdf", 1),
        _document("rfp", "main", "Case service", "rfp.pdf", 2),
        _document("annexb", "annex", "Annex B Requirements", "annex_b.xlsx", 3),
    ],
)


class Corpus:
    """Passages and requirements built in reading order, one requirement per passage."""

    def __init__(self) -> None:
        self.passages: dict[str, Passage] = {}
        self.requirements: list[Requirement] = []

    def add(self, doc: str, section: str, quote: str, disposition: str = "BINDING") -> str:
        number = len(self.passages) + 1
        src = f"SRC-{number:04d}"
        self.passages[src] = Passage(
            id=src,
            doc_id=doc,
            section_path=section,
            kind="sentence",
            text=quote,
            start=number * 1000,
            end=number * 1000 + len(quote),
        )
        rid = f"REQ-{number:04d}"
        self.requirements.append(
            Requirement.model_validate(
                {
                    "id": rid,
                    "doc_id": doc,
                    "statement": quote,
                    "modality": "shall",
                    "mandatory": disposition == "BINDING",
                    "hazard": False,
                    "disposition": disposition,
                    "src_ids": [src],
                    "quote": quote,
                    "quote_status": "VERBATIM_VERIFIED",
                }
            )
        )
        return rid

    def unique(self, doc: str, section: str) -> str:
        """A requirement whose words share nothing with any other."""
        n = len(self.passages)
        words = " ".join(f"{WORDS[n % 26]}{WORDS[(n // 26) % 26]}{i}" for i in range(4))
        return self.add(doc, section, f"The Supplier shall provide {words}.")

    def clusters(self, register: ControlRegister | None = REGISTER) -> list:
        return build_clusters(self.requirements, self.passages, register, LIMITS)


def test_base_clusters_group_a_document_section_and_skip_other_dispositions() -> None:
    corpus = Corpus()
    a = corpus.unique("rfp", "4 Requirements > 4.1 Signing")
    b = corpus.unique("rfp", "4 Requirements > 4.2 Records")
    c = corpus.unique("rfp", "5 Service levels")
    corpus.add(
        "rfp", "5 Service levels", "The Council keeps a history of the service.", "BACKGROUND"
    )
    members = [cluster.members for cluster in corpus.clusters()]
    assert members == [[a, b], [c]], "BACKGROUND requirements are not members"


def test_a_large_section_splits_by_its_second_segment_then_into_runs_of_twelve() -> None:
    corpus = Corpus()
    first = [corpus.unique("rfp", "6 Functions > 6.1 Cases") for _ in range(15)]
    second = [corpus.unique("rfp", "6 Functions > 6.2 Reports") for _ in range(3)]
    members = [cluster.members for cluster in corpus.clusters()]
    assert members == [first[:12], first[12:], second]


def test_an_addendum_section_reference_joins_the_main_document_cluster() -> None:
    corpus = Corpus()
    main = corpus.unique("rfp", "4 Requirements > 4.2 Records")
    other = corpus.unique("rfp", "7 Training")
    late = corpus.add("add", "Addendum 1", "Section 4.2 now requires ten year retention periods.")
    clusters = corpus.clusters()
    assert [c.members for c in clusters] == [[main, late], [other]]
    assert clusters[0].addendum and clusters[0].linked


def test_a_section_reference_joins_the_first_cluster_holding_that_section() -> None:
    corpus = Corpus()
    target = corpus.unique("rfp", "5 Service levels")
    corpus.unique("rfp", "6 Support")
    pointer = corpus.add("rfp", "8 Exit", "Exit support follows the rules of Clause 5 throughout.")
    clusters = corpus.clusters()
    assert clusters[0].members == [target, pointer]


def test_an_annex_reference_joins_the_first_cluster_of_that_document() -> None:
    corpus = Corpus()
    pointer = corpus.add("rfp", "3 Scope", "Deliver every function listed in Annex B promptly.")
    corpus.unique("rfp", "9 Pricing")
    annex = corpus.unique("annexb", "Requirements")
    clusters = corpus.clusters()
    assert clusters[0].members == [pointer, annex], "the annex cluster merges into the pointer's"


def test_near_duplicates_join_the_earlier_cluster() -> None:
    corpus = Corpus()
    early = corpus.add(
        "rfp", "4 Backups", "The Supplier shall encrypt nightly backups with strong keys."
    )
    corpus.unique("rfp", "5 Hosting")
    late = corpus.add(
        "rfp", "9 Security", "The Supplier shall encrypt nightly backups with strong keys always."
    )
    clusters = corpus.clusters()
    assert clusters[0].members == [early, late]


def test_over_the_cap_the_other_cluster_joins_as_nearest_context() -> None:
    corpus = Corpus()
    big = [corpus.unique("rfp", "4 Requirements") for _ in range(11)]
    pointer = corpus.add("rfp", "4 Requirements", "Comply with Clause 6 in full for every case.")
    others = [corpus.unique("rfp", "6 Reports") for _ in range(10)]
    clusters = corpus.clusters()
    giving = next(c for c in clusters if pointer in c.members)
    receiving = next(c for c in clusters if others[0] in c.members)
    assert giving.members == [*big, pointer] and receiving.members == others, "no merge over 12"
    nearest = [*big[4:], pointer]  # the 8 nearest in reading order to the receiving cluster
    assert receiving.context == nearest and giving.context == []
    assert receiving.linked and giving.linked
    every = [m for c in clusters for m in c.members]
    assert sorted(every) == sorted(r.id for r in corpus.requirements), "each member exactly once"


def test_singletons_and_numbering() -> None:
    corpus = Corpus()
    lone = corpus.unique("rfp", "2 Background")
    pair = [corpus.unique("rfp", "4 Requirements") for _ in range(2)]
    clusters = corpus.clusters(register=None)
    assert [(c.group_id, c.members, c.to_model) for c in clusters] == [
        ("RG-001", [lone], False),
        ("RG-002", pair, True),
    ]


def test_the_precedence_clause_goes_to_addendum_clusters_only() -> None:
    corpus = Corpus()
    main = corpus.unique("rfp", "4 Requirements > 4.2 Records")
    corpus.add("add", "Addendum 1", "Section 4.2 now requires ten year retention periods.")
    clause = corpus.add(
        "rfp", "1 General", "In the event of any conflict, the latest addendum shall prevail."
    )
    clusters = corpus.clusters()
    found = precedence_passages(list(corpus.passages.values()))
    assert [p.id for p in found] == [corpus.requirements[-1].src_ids[0]]
    by_id = {r.id: r for r in corpus.requirements}
    with_addendum = next(c for c in clusters if main in c.members)
    plain = next(c for c in clusters if clause in c.members)
    task = cluster_task(with_addendum, by_id, corpus.passages, register=REGISTER, precedence=found)
    assert [v.src_id for v in task.precedence_clause] == [found[0].id]
    assert [e.role for e in task.precedence] == ["addendum", "main", "annex"]
    assert cluster_task(plain, by_id, corpus.passages, precedence=found).precedence_clause == []
