"""Unit tests for university name canonicalization."""
from __future__ import annotations

from app.services.university_normalizer import ALIAS_MAP, canonicalize

# ---------------------------------------------------------------------------
# IIT variants
# ---------------------------------------------------------------------------

def test_iit_full_name_bombay() -> None:
    assert canonicalize("Indian Institute of Technology Bombay") == "iit bombay"


def test_iit_short_name_bombay() -> None:
    assert canonicalize("IIT Bombay") == "iit bombay"


def test_iit_abbreviation_iitb() -> None:
    assert canonicalize("IITB") == "iit bombay"


def test_iit_all_three_variants_equal() -> None:
    variants = [
        "Indian Institute of Technology Bombay",
        "IIT Bombay",
        "IITB",
    ]
    canonicals = [canonicalize(v) for v in variants]
    assert len(set(canonicals)) == 1, f"Expected 1 unique canonical, got: {canonicals}"


def test_iit_delhi_distinct_from_bombay() -> None:
    assert canonicalize("IIT Delhi") != canonicalize("IIT Bombay")


def test_iit_delhi_full_name() -> None:
    assert canonicalize("Indian Institute of Technology Delhi") == canonicalize("IIT Delhi")


def test_iit_madras_abbreviation() -> None:
    assert canonicalize("IITM") == "iit madras"


def test_iit_kanpur_abbreviation() -> None:
    assert canonicalize("IITK") == "iit kanpur"


# ---------------------------------------------------------------------------
# NIT variants
# ---------------------------------------------------------------------------

def test_nit_trichy_short() -> None:
    assert canonicalize("NIT Trichy") == "nit tiruchirappalli"


def test_nit_trichy_full_name() -> None:
    assert canonicalize("National Institute of Technology Tiruchirappalli") == "nit tiruchirappalli"


def test_nit_trichy_variants_equal() -> None:
    assert canonicalize("NIT Trichy") == canonicalize("National Institute of Technology Tiruchirappalli")


def test_nit_different_cities_distinct() -> None:
    assert canonicalize("NIT Surathkal") != canonicalize("NIT Trichy")


# ---------------------------------------------------------------------------
# IIIT variants
# ---------------------------------------------------------------------------

def test_iiit_full_name() -> None:
    assert canonicalize("Indian Institute of Information Technology Hyderabad") == "iiit hyderabad"


def test_iiit_short_name() -> None:
    assert canonicalize("IIIT Hyderabad") == "iiit hyderabad"


def test_iiit_variants_equal() -> None:
    assert (
        canonicalize("Indian Institute of Information Technology Hyderabad")
        == canonicalize("IIIT Hyderabad")
    )


# ---------------------------------------------------------------------------
# IISc
# ---------------------------------------------------------------------------

def test_iisc_abbreviation() -> None:
    assert canonicalize("IISc") == "iisc bangalore"


def test_iisc_full_name() -> None:
    assert canonicalize("Indian Institute of Science") == "iisc bangalore"


def test_iisc_bengaluru_variant() -> None:
    assert canonicalize("IISc Bengaluru") == "iisc bangalore"


# ---------------------------------------------------------------------------
# Global universities — generic slug
# ---------------------------------------------------------------------------

def test_stanford_with_university_suffix() -> None:
    assert canonicalize("Stanford University") == "stanford"


def test_stanford_bare() -> None:
    assert canonicalize("Stanford") == "stanford"


def test_stanford_variants_equal() -> None:
    assert canonicalize("Stanford University") == canonicalize("Stanford")


def test_mit_abbreviation() -> None:
    assert canonicalize("MIT") == "mit"


def test_mit_full_name() -> None:
    assert canonicalize("Massachusetts Institute of Technology") == "mit"


def test_carnegie_mellon_full() -> None:
    assert canonicalize("Carnegie Mellon University") == "carnegie mellon"


def test_carnegie_mellon_abbreviation() -> None:
    assert canonicalize("CMU") == "carnegie mellon"


def test_georgia_tech_alias() -> None:
    assert canonicalize("Georgia Tech") == "georgia institute of technology"


def test_georgia_tech_full_name() -> None:
    assert canonicalize("Georgia Institute of Technology") == "georgia institute of technology"


def test_georgia_tech_variants_equal() -> None:
    assert canonicalize("Georgia Tech") == canonicalize("Georgia Institute of Technology")


def test_eth_zurich_alias() -> None:
    assert canonicalize("ETH Zurich") == "eth zurich"


def test_eth_abbreviation() -> None:
    assert canonicalize("ETH") == "eth zurich"


def test_university_of_toronto() -> None:
    result = canonicalize("University of Toronto")
    assert result == "toronto"


def test_uc_berkeley_alias() -> None:
    assert canonicalize("UC Berkeley") == "california berkeley"


def test_uc_berkeley_full_name() -> None:
    assert canonicalize("University of California Berkeley") == "california berkeley"


def test_uc_berkeley_variants_equal() -> None:
    assert canonicalize("UC Berkeley") == canonicalize("University of California Berkeley")


# ---------------------------------------------------------------------------
# Distinct campuses stay distinct
# ---------------------------------------------------------------------------

def test_iit_different_cities_are_distinct() -> None:
    assert canonicalize("IIT Bombay") != canonicalize("IIT Delhi")
    assert canonicalize("IIT Madras") != canonicalize("IIT Kanpur")


def test_bits_campuses_distinct() -> None:
    assert canonicalize("BITS Pilani") != canonicalize("BITS Hyderabad")
    assert canonicalize("BITS Hyderabad") != canonicalize("BITS Goa")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_string_returns_empty() -> None:
    assert canonicalize("") == ""


def test_whitespace_only_returns_empty() -> None:
    assert canonicalize("   ") == ""


def test_case_insensitive() -> None:
    assert canonicalize("iit bombay") == canonicalize("IIT BOMBAY")


def test_punctuation_stripped() -> None:
    assert canonicalize("I.I.T. Bombay") == "iit bombay"


def test_leading_the_stripped() -> None:
    assert canonicalize("The University of Melbourne") == canonicalize("University of Melbourne")


def test_alias_map_values_are_lowercase() -> None:
    for key, value in ALIAS_MAP.items():
        assert value == value.lower(), f"ALIAS_MAP value not lowercase: {key!r} -> {value!r}"
