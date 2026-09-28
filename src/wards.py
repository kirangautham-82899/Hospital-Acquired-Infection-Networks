"""Shared person/ward-group mapping used across phases (audit, network,
states, ...). Single source of truth so P1's audit and P2's network build
(and later phases) agree on who is PA/PE and which ward group each person
belongs to.
"""
import config


def person_prefix(ident_series):
    """Return 'PA', 'PE', or 'OTHER' for each calc_ident string, based on
    its leading prefix (e.g. 'PA-001-LAM' -> 'PA')."""
    prefix = ident_series.str.split("-").str[0]
    return prefix.where(prefix.isin(["PA", "PE"]), "OTHER")


def map_to_ward_group(service_series):
    """Map a raw service_pa_pe value to one of the 6 locked ward groups:
    the 5 real wards pass through unchanged, the 4 staff-only services
    collapse to 'Other', and anything else comes back as 'UNMAPPED' so
    callers can flag it instead of silently misclassifying people."""
    def _map(value):
        if value in config.OTHER_SERVICES:
            return "Other"
        if value in [g for g in config.WARD_GROUPS if g != "Other"]:
            return value
        return "UNMAPPED"
    return service_series.map(_map)


def person_ward_map(admission):
    """Return a dict {calc_ident: ward_group} built from admission.csv,
    using map_to_ward_group. Convenience lookup for network/state code
    that needs to assign a ward to a person by id."""
    ward_group = map_to_ward_group(admission["service_pa_pe"])
    return dict(zip(admission["calc_ident"], ward_group))
