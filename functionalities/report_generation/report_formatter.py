#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Report Data Builder
===================

Builds the structured pieces of the report that the WeasyPrint template renders
but the per-category pipeline components don't produce directly:

- risk indicators  -> cover verdict tiles
- management priority matrix
- KPI tiles
- per-section blocks (facts / classification / clouds / tables / notes)
- references list (databases + research, numbered or APA ordering)
- report metadata rows

This is plain data-shaping logic reused by the report renderer's
build_report_context() — not a Haystack component. The per-entry citation
formatters and the translation/metadata lookups are preserved verbatim from the
former markdown formatter; only the markdown assembly was removed.
"""

import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

_INTERNAL_LABELS = {'AI-normalization', 'Unknown', 'Research Source'}

# Canonical taxonomic ranks, in display order — drives the classification table.
_RANK_ORDER = ['kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']

# Vernacular/common-name fields → the per-language flagged vernacular table.
_VERNACULAR_FIELDS = ('vernacular_names', 'common_names')

# Distribution fields consumed by dedicated renderers (countries table + the map),
# so the generic record router skips them in distribution_and_status.
_COUNTRY_FIELDS = ('normalized_countries', 'present_in_countries')

# Section fields never rendered as a generic block: rendered elsewhere (rank
# fields + taxonomy → classification; distribution_records → appendix) or
# summarised instead of dumped (occurrence_sample → a count tile + the map).
_OMIT_SECTION_FIELDS = frozenset(
    set(_RANK_ORDER) | {'taxonomy', 'distribution_records', 'occurrence_sample'}
)

# Record-table columns are curated for A4: drop machine/noise keys (ids, links,
# refs, raw coordinates) and cap the rest, so wide source records stay scannable.
_MAX_TABLE_COLS = 6
_NOISE_COL_RE = re.compile(
    r'(id|key|link|url|ref|uncertainty|latitude|longitude|coordinate|elevation|'
    r'depth|timestamp|datasetkey|gbifid|index)', re.I)
_DB_FULL_NAMES = {
    'GBIF': 'Global Biodiversity Information Facility',
    'WRiMS': 'World Register of Marine Species',
    'WoRMS': 'World Register of Marine Species',
    'IUCN': 'IUCN Red List of Threatened Species',
    'EASIN': 'European Alien Species Information Network',
    'AquaNIS': 'Information System on Aquatic Non-Indigenous Species',
    'CABI': 'CABI Compendium',
}

# External-identifier keys → the database that issues them. Curated so only real
# identifiers become chips (no junk keys leak in). Covers both the top-level
# data_metadata fields (easin_id) and the keys nested inside the per-source
# metadata blocks (metadata.value: gbif_key/aphia_id/aquanis_id) and WRiMS
# external_references (tsn/gisd/ncbi/bold).
_EXTERNAL_ID_LABELS = {
    'easin_id': 'EASIN', 'easinid': 'EASIN',
    'gbif_key': 'GBIF', 'taxon_key': 'GBIF',
    'aphia_id': 'WoRMS', 'aphiaid': 'WoRMS',
    'aquanis_id': 'AquaNIS',
    'tsn': 'ITIS', 'gisd': 'GISD', 'ncbi': 'NCBI', 'bold': 'BOLD',
}
# data_metadata fields whose value is a dict aggregating a source's identifiers.
_NESTED_ID_FIELDS = ('metadata', 'external_references')

# IUCN Red List category codes → full names, for the conservation-status line.
_IUCN_CATEGORY_NAMES = {
    'LC': 'Least Concern', 'NT': 'Near Threatened', 'VU': 'Vulnerable',
    'EN': 'Endangered', 'CR': 'Critically Endangered', 'EW': 'Extinct in the Wild',
    'EX': 'Extinct', 'DD': 'Data Deficient', 'NE': 'Not Evaluated',
}


class ReportDataBuilder:
    """Shapes cleaned pipeline data into the structured report blocks."""

    # =====================================================================
    # COVER VERDICT  (derived from the Risk Summary indicators)
    # =====================================================================
    def build_risk_indicators(
        self, cleaned_data: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        """Derive the headline risk indicators as (label, value) pairs.

        Derives 5 indicators from cleaned_data (the original pre-extractor
        snapshot): EU Reg. 1143/2014 listing, invasion stage, EICAT, SEICAT,
        IUCN Red List, Horizon Scanning. Values default to '—' when absent.
        """
        def _best_fact(category: str, field: str):
            entries = cleaned_data.get(category, {}).get(field, [])
            if not entries:
                return None
            for agreement in ('consensus', 'single', 'minority'):
                for e in entries:
                    if e.get('agreement') == agreement:
                        return e.get('fact')
            return entries[0].get('fact') if entries else None

        rows: List[Tuple[str, str]] = []

        # ── EU Regulation 1143/2014 ──────────────────────────────────────
        is_eu = _best_fact('management_biosecurity', 'is_eu_concern')
        if is_eu is None:
            is_eu = _best_fact('distribution_and_status', 'is_eu_concern')
        entry_into_force = _best_fact('management_biosecurity', 'entry_into_force')
        if is_eu is True or (isinstance(is_eu, str) and is_eu.lower() in ('true', 'yes', '1')):
            eu_val = "Union Concern"
            if entry_into_force:
                if isinstance(entry_into_force, dict):
                    date_val = (entry_into_force.get('description')
                                or next((v for v in entry_into_force.values() if v), ''))
                else:
                    date_val = str(entry_into_force)
                if date_val:
                    eu_val += f" (listed {date_val})"
        elif is_eu is False or (isinstance(is_eu, str) and is_eu.lower() in ('false', 'no', '0')):
            eu_val = "Not listed"
        else:
            eu_val = "—"
        rows.append(("EU Reg. 1143/2014", eu_val))

        # ── Invasion Stage ───────────────────────────────────────────────
        countries_raw = _best_fact('distribution_and_status', 'present_in_countries')
        if countries_raw and isinstance(countries_raw, str):
            country_count = len(countries_raw.split())
            if country_count > 10:
                stage = f"Established ({country_count} countries/territories)"
            elif country_count > 3:
                stage = f"Spreading ({country_count} countries/territories)"
            else:
                stage = f"Detected ({country_count} countries/territories)"
        elif isinstance(countries_raw, list):
            country_count = len(countries_raw)
            stage = f"{'Established' if country_count > 10 else 'Spreading' if country_count > 3 else 'Detected'} ({country_count} countries/territories)"
        else:
            stage = "—"
        rows.append(("Invasion Stage", stage))

        # ── EICAT / SEICAT ───────────────────────────────────────────────
        eicat = (_best_fact('impacts', 'eicat_score')
                 or _best_fact('impacts', 'eicat_assessment')
                 or _best_fact('impacts', 'eicat_classification'))
        rows.append(("EICAT", str(eicat) if eicat else "—"))

        seicat = (_best_fact('impacts', 'seicat_score')
                  or _best_fact('impacts', 'seicat_assessment')
                  or _best_fact('impacts', 'seicat_classification'))
        rows.append(("SEICAT", str(seicat) if seicat else "—"))

        # ── IUCN Red List ────────────────────────────────────────────────
        iucn = (_best_fact('taxonomic_identity', 'iucn_red_list')
                or _best_fact('impacts', 'iucn_red_list')
                or _best_fact('taxonomic_identity', 'iucn_category')
                or _best_fact('taxonomic_identity', 'conservation_status')
                or _best_fact('management_biosecurity', 'conservation_status'))
        rows.append(("IUCN Red List", str(iucn) if iucn else "—"))

        # ── Horizon Scanning ─────────────────────────────────────────────
        hs = _best_fact('management_biosecurity', 'is_horizon_scanning')
        if hs is True:
            hs_val = "Yes"
        elif hs is False:
            hs_val = "No"
        else:
            hs_val = "—"
        rows.append(("Horizon Scanning", hs_val))

        return rows

    # =====================================================================
    # MANAGEMENT PRIORITY MATRIX
    # =====================================================================
    def build_management_matrix(
        self, cleaned_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Return {columns, rows} for the management-priority table, or None.

        Populated from cleaned management_biosecurity fields where available;
        explicit '—' cells for gaps make the data absence visible (E4.3).
        """
        mgmt = cleaned_data.get('management_biosecurity', {})
        if not mgmt:
            return None

        _method_fields = {
            'mechanical_control': 'Mechanical control',
            'chemical_control': 'Chemical control',
            'biological_control': 'Biological control',
            'trapping': 'Trapping',
            'electrofishing': 'Electrofishing',
            'eradication': 'Eradication',
            'containment': 'Containment',
            'surveillance': 'Surveillance / monitoring',
            'prevention': 'Prevention / biosecurity',
        }
        _non_method_fields = frozenset({
            'is_eu_concern', 'is_ms_concern', 'is_outermost_concern',
            'is_horizon_scanning', 'concerned_outermost_regions',
            'concerned_member_states', 'entry_into_force',
            'study_design_type', 'study_duration',
        })

        def _best_entry(entries):
            if not entries:
                return None
            return next(
                (e for e in entries if e.get('agreement') in ('consensus', 'single')),
                entries[0]
            )

        def _fact_snippet(fact) -> str:
            if fact is None:
                return '—'
            s = ' '.join(str(fact).split()).strip()
            return (s[:80] + '…') if len(s) > 80 else s or '—'

        def _row_sources(entry) -> str:
            """Visible source keys for the row, joined for the src_chips macro."""
            if not entry:
                return '—'
            vis = [s for s in entry.get('sources', []) if s not in _INTERNAL_LABELS]
            return ' · '.join(dict.fromkeys(vis)) or '—'

        rows: List[List[str]] = []

        for field, label in _method_fields.items():
            best = _best_entry(mgmt.get(field, []))
            if best:
                rows.append([label, _fact_snippet(best.get('fact')),
                             '—', '—', '—', _row_sources(best)])

        for field, entries in mgmt.items():
            if field in _method_fields or field in _non_method_fields:
                continue
            best = _best_entry(entries)
            if not best:
                continue
            rows.append([field.replace('_', ' ').title(),
                         _fact_snippet(best.get('fact')),
                         '—', '—', '—', _row_sources(best)])

        columns = ["Method / Evidence", "Detail", "Estimated Cost",
                   "Feasibility", "Priority", "Source"]
        if not rows:
            rows = [["—", "No management method data in sources", "—", "—", "—", "—"]]
        # source_col → template renders that column as clickable source chips.
        return {"columns": columns, "rows": rows, "source_col": 5}

    # =====================================================================
    # KPI TILES
    # =====================================================================
    def build_kpis(
        self, cleaned_data: Dict[str, Any], source_count: int
    ) -> List[Dict[str, str]]:
        """Return up to 4 headline {value, label} tiles, omitting absent ones.

        Counts come from record-list fields in the pre-extractor snapshot
        (introduction/pathway/source-region records); a tile is dropped when its
        field is missing rather than shown as zero.
        """
        dist = cleaned_data.get('distribution_and_status', {})
        paths = cleaned_data.get('introduction_pathways', {})

        intro = self._record_count(dist.get('introduction_records'))
        regions = self._record_count(dist.get('source_regions'))
        occurrences = self._record_count(dist.get('occurrence_sample'))
        pathways = sum(
            self._record_count(paths.get(f))
            for f in ('pathways_aquanis', 'pathways_easin', 'cbd_pathways')
        )

        tiles: List[Dict[str, str]] = []
        if intro:
            tiles.append({"value": str(intro), "label": "recorded introductions"})
        if regions:
            tiles.append({"value": str(regions), "label": "source regions of introduction"})
        if occurrences:
            tiles.append({"value": str(occurrences), "label": "occurrence records (GBIF)"})
        if pathways:
            tiles.append({"value": str(pathways), "label": "pathway records"})
        if source_count:
            tiles.append({"value": str(source_count), "label": "sources reconciled"})
        return tiles

    @staticmethod
    def _record_count(entries: Optional[List[Dict[str, Any]]]) -> int:
        """Number of records carried by a field's best entry (its fact is a list)."""
        if not entries:
            return 0
        fact = entries[0].get('fact')
        return len(fact) if isinstance(fact, list) else (1 if fact else 0)

    # =====================================================================
    # PER-SECTION BLOCKS  (facts / classification / clouds / tables / notes)
    # =====================================================================
    def build_section_blocks(
        self, category: str, category_fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Partition one category's cleaned fields into the template's section
        blocks by value shape — the single routing policy that replaces the old
        stringify-everything-into-a-fact path.

        Routing (nothing is dropped — every field lands in some block):
          - scalar (str/bool/number)        -> fact card ("Label: value")
          - taxonomic rank fields/taxonomy  -> classification table (+ conflict)
          - vernacular/common name lists    -> per-language flagged table
          - country lists (distribution)    -> flagged countries-&-status table
          - list of scalars                 -> chip cloud (unioned across sources)
          - list of dicts (records)         -> curated table (single field -> cloud)
          - any other shape                 -> "Label: value" fact (fallback)
        """
        from functionalities.report_generation.display_utils import humanize_field_name

        blocks: Dict[str, Any] = {
            "facts": [], "classification": None, "conflict": None,
            "clouds": [], "tables": [], "notes": [],
        }
        handled = set(_OMIT_SECTION_FIELDS)

        if category == 'taxonomic_identity':
            blocks["classification"], blocks["conflict"] = self._classification(category_fields)
            # Vernacular/common names → one per-language flagged table.
            vern = self._vernacular_table(
                [e for f in _VERNACULAR_FIELDS for e in category_fields.get(f, [])])
            if vern:
                blocks["tables"].append(vern)
            handled.update(_VERNACULAR_FIELDS)

        if category == 'distribution_and_status':
            countries = self._countries_table(category_fields)
            if countries:
                blocks["tables"].append(countries)
            handled.update(_COUNTRY_FIELDS)

        for field, entries in category_fields.items():
            if field in handled or not isinstance(entries, list) or not entries:
                continue

            label = humanize_field_name(field)
            best = self._best_entry(entries)
            if not best:
                continue
            fact = best.get('fact')

            if self._is_research_only(best.get('sources', [])):
                continue  # represented by the section's evidence block, not a card

            # IUCN conservation status is a structured dict with no description
            # key — format it to one clean line instead of dumping the raw dict.
            if field == 'conservation_status' and isinstance(fact, dict):
                text = self._format_conservation_status(fact)
                if text:
                    blocks["facts"].append({
                        "fact": text,
                        "sources": best.get('sources', []),
                        "agreement": best.get('agreement', 'single'),
                    })
                continue

            if self._is_scalar(fact):
                blocks["facts"].append({
                    "fact": f"{label}: {self._scalar_str(fact)}",
                    "sources": best.get('sources', []),
                    "agreement": best.get('agreement', 'single'),
                    "translated_from": best.get('translated_from'),
                })
            elif isinstance(fact, list) and fact and isinstance(fact[0], dict):
                # records — gather across ALL entries so no source's rows are lost
                records = [r for e in entries
                           for r in (e.get('fact') or []) if isinstance(r, dict)]
                self._route_records(blocks, label, records, self._all_sources(entries))
            elif isinstance(fact, list):
                # scalar list (e.g. synonyms) — union the lists across all entries.
                # Synonyms get author/year stripped first so the same name from
                # different databases dedups to one chip carrying every source.
                cloud = self._scalar_cloud(
                    label, entries, normalize='synonym' in field.lower())
                if cloud:
                    blocks["clouds"].append(cloud)
            else:
                # unmatched shape (e.g. a non-taxonomy dict): never drop it —
                # render its readable label so a card stays concise
                blocks["facts"].append({
                    "fact": f"{label}: {self._chip_text(fact)}",
                    "sources": best.get('sources', []),
                    "agreement": best.get('agreement', 'single'),
                    "translated_from": best.get('translated_from'),
                })

        return blocks

    @staticmethod
    def _is_research_only(sources: List[str]) -> bool:
        """True when every source is a research paper (not a known database and
        not an internal label) — such facts are shown in the evidence block."""
        real = [s for s in sources if s not in _INTERNAL_LABELS]
        return bool(real) and all(s not in _DB_FULL_NAMES for s in real)

    @staticmethod
    def _all_sources(entries: List[Dict[str, Any]]) -> List[str]:
        """Union of sources across a field's entries, in first-seen order."""
        out: List[str] = []
        for e in entries:
            for s in e.get('sources', []):
                if s not in out:
                    out.append(s)
        return out

    def _scalar_cloud(self, label: str, entries: List[Dict[str, Any]],
                      normalize: bool = False) -> Optional[Dict[str, Any]]:
        """List-of-scalar fields (synonyms, codes) → one deduped chip cloud,
        unioned across every source's list so nothing is dropped. Each chip keeps
        EVERY database that reported it (sources), so all provenance links survive
        instead of collapsing to one. With `normalize`, author/year is stripped
        from each value (synonyms) so the same name from different databases
        dedups together. Dict items in a mixed list are coerced to a readable
        label rather than dumped raw."""
        seen: Dict[str, Dict[str, Any]] = {}
        items: List[Dict[str, Any]] = []
        for entry in entries:
            fact = entry.get('fact')
            srcs = [s for s in entry.get('sources', []) if s not in _INTERNAL_LABELS]
            for v in (fact if isinstance(fact, list) else [fact]):
                if v is None:
                    continue
                text = self._chip_text(v)
                if not text:
                    continue
                if normalize:
                    text = self._strip_author(text)
                item = seen.get(text.lower())
                if item is None:
                    item = {"text": text, "sources": []}
                    seen[text.lower()] = item
                    items.append(item)
                for s in srcs:
                    if s not in item["sources"]:
                        item["sources"].append(s)
        return {"label": label, "items": items} if items else None

    @staticmethod
    def _strip_author(text: str) -> str:
        """Reduce a synonym string to its scientific name (genus + epithets),
        dropping author/year so the same name from different databases dedups to
        one chip. 'Oncorhynchus scouleri (Richardson, 1836)' and 'Oncorhynchus
        scouleri' → 'Oncorhynchus scouleri'. Non-name strings return unchanged."""
        t = re.sub(r'\([^)]*\)', ' ', text)   # parenthetical author, e.g. (Richardson, 1836)
        t = t.split(',')[0]                    # trailing ", 1836" / author after a comma
        tokens = t.split()
        out: List[str] = []
        for i, tok in enumerate(tokens):
            if i == 0:
                out.append(tok)                       # genus (or the whole single word)
            elif tok.isalpha() and tok[:1].islower():
                out.append(tok)                       # species / subspecies epithet
            else:
                break                                 # author token (Capitalised / & / year) → stop
        return ' '.join(out) if out else text.strip()

    def _format_conservation_status(self, d: Dict[str, Any]) -> Optional[str]:
        """IUCN conservation_status dict → one readable line, e.g.
        "IUCN Red List: Least Concern (LC) · population increasing · assessed 2010".
        Returns None when there's no category to anchor the line."""
        cat = str(d.get('iucn_category') or '').strip()
        if not cat:
            return None
        name = _IUCN_CATEGORY_NAMES.get(cat.upper(), cat)
        parts = [f"IUCN Red List: {name} ({cat})" if name != cat
                 else f"IUCN Red List: {cat}"]
        trend = d.get('population_trend')
        if isinstance(trend, dict):
            desc = trend.get('description')
            if isinstance(desc, dict):
                desc = desc.get('en') or next((v for v in desc.values() if v), '')
            if desc:
                parts.append(f"population {str(desc).strip().lower()}")
        date = d.get('assessment_date')
        if date:
            parts.append(f"assessed {date}")
        return " · ".join(parts)

    def _chip_text(self, value: Any) -> str:
        """A short readable chip label for a scalar or a small dict (prefers a
        description/name/value key, else a compact join)."""
        if isinstance(value, dict):
            for key in ('description', 'name', 'Name', 'value', 'label'):
                if value.get(key):
                    return self._chip_text(value[key])
            return self._cell(value)
        if isinstance(value, (list, tuple)):
            return self._cell(value)
        return self._scalar_str(value)

    def _route_records(
        self, blocks: Dict[str, Any], label: str,
        records: List[Dict[str, Any]], sources: List[str],
    ) -> None:
        """Send a list of record dicts to the right block: a chip cloud when the
        records carry a single content field, else a table of curated columns
        (machine/noise keys dropped, the rest capped to A4-readable width)."""
        if not records:
            return
        all_cols = self._union_cols(records)
        cols = [c for c in all_cols if not _NOISE_COL_RE.search(c)] or all_cols

        if len(cols) == 1:
            col = cols[0]
            seen, items = set(), []
            for rec in records:
                text = self._cell(rec.get(col))
                if text != "—" and text.lower() not in seen:
                    seen.add(text.lower())
                    items.append({"text": text})
            if items:
                blocks["clouds"].append({"label": label, "items": items})
            return

        table = self._records_table(label, records, cols[:_MAX_TABLE_COLS], sources)
        if table:
            blocks["tables"].append(table)

    def _classification(
        self, fields: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Build the consensus classification table and an optional conflict
        callout from the `taxonomy` dict and/or individual rank fields."""
        consensus: Dict[str, Any] = {}      # rank -> {value, entry}
        tax = self._best_entry(fields.get('taxonomy', []))
        if tax and isinstance(tax.get('fact'), dict):
            for rank, val in tax['fact'].items():
                if rank in _RANK_ORDER and val:
                    consensus[rank] = {"value": str(val), "entry": tax}

        for rank in _RANK_ORDER:
            entry = self._best_entry(fields.get(rank, []))
            if entry and self._is_scalar(entry.get('fact')) and rank not in consensus:
                consensus[rank] = {"value": self._scalar_str(entry['fact']), "entry": entry}

        if not consensus:
            return None, None

        rows = [[rank.title(), consensus[rank]["value"]]
                for rank in _RANK_ORDER if rank in consensus]
        classification = {"caption": "Consensus classification", "rows": rows}

        # Conflict: an individual rank field that disagrees with the consensus dict.
        conflict_rows = []
        for rank in _RANK_ORDER:
            alt = self._best_entry(fields.get(rank, []))
            if not (alt and self._is_scalar(alt.get('fact')) and rank in consensus):
                continue
            alt_val = self._scalar_str(alt['fact'])
            if alt_val.lower() != consensus[rank]["value"].lower():
                conflict_rows.append(self._conflict_row(rank, consensus[rank]["value"],
                                                        consensus[rank]["entry"]))
                conflict_rows.append(self._conflict_row(rank, alt_val, alt))

        conflict = ({"title": "Higher classification disagrees", "rows": conflict_rows}
                    if conflict_rows else None)
        return classification, conflict

    @staticmethod
    def _conflict_row(rank: str, value: str, entry: Dict[str, Any]) -> Dict[str, str]:
        sources = entry.get('sources') or []
        return {
            "value": f"{rank.title()} · {value}",
            "source": " · ".join(sources) if sources else "—",
        }

    def _vernacular_table(self, entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Vernacular/common names → one table grouped by language, each row a
        language name + the comma-joined names (the UI's grouped display)."""
        from frontend.utils.flags import normalize_language_name

        groups: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []
        for entry in entries:
            fact = entry.get('fact')
            if not isinstance(fact, list):
                continue
            for item in fact:
                if not isinstance(item, dict):
                    continue
                name = (item.get('name') or item.get('Name') or '').strip()
                if not name:
                    continue
                raw_lang = (item.get('language') or '').strip()
                lang_name = normalize_language_name(raw_lang) or (raw_lang.title() or 'Other')
                key = lang_name.lower()
                if key not in groups:
                    groups[key] = {"label": lang_name, "names": [], "seen": set()}
                    order.append(key)
                g = groups[key]
                if name.lower() not in g["seen"]:
                    g["seen"].add(name.lower())
                    g["names"].append(name)
        if not order:
            return None
        order.sort(key=lambda k: (-len(groups[k]["names"]), groups[k]["label"]))
        rows = [[groups[k]["label"], ", ".join(groups[k]["names"])] for k in order]
        return {"caption": "Vernacular names", "columns": ["Language", "Names"],
                "rows": rows}

    def _countries_table(self, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Distribution countries → a table. Prefers normalized_countries
        ({iso2, status}); falls back to present_in_countries (names, no status)."""
        from frontend.utils.flags import country_code_to_name

        nc = self._best_entry(fields.get('normalized_countries', []))
        if nc and isinstance(nc.get('fact'), list):
            triples, seen = [], set()
            for rec in nc['fact']:
                if not isinstance(rec, dict):
                    continue
                iso2 = (rec.get('iso2') or '').strip().upper()
                if not iso2 or iso2 in seen:
                    continue
                seen.add(iso2)
                status = (rec.get('status') or '').strip().title() or '—'
                triples.append((country_code_to_name(iso2), status))
            if triples:
                triples.sort(key=lambda t: t[0])
                return {"caption": "Countries & status", "columns": ["Country", "Status"],
                        "rows": [[t[0], t[1]] for t in triples]}

        pc = self._best_entry(fields.get('present_in_countries', []))
        if pc and isinstance(pc.get('fact'), list):
            names, seen = [], set()
            for rec in pc['fact']:
                n = (rec.get('Country') if isinstance(rec, dict) else rec) or ''
                n = str(n).strip()
                if n and n.lower() not in seen:
                    seen.add(n.lower())
                    names.append(n)
            if names:
                names.sort()
                return {"caption": "Countries", "columns": ["Country", "Status"],
                        "rows": [[n, '—'] for n in names]}
        return None

    @staticmethod
    def _union_cols(records: List[Dict[str, Any]]) -> List[str]:
        """Keys across records, in first-seen order."""
        cols: List[str] = []
        for rec in records:
            for k in rec.keys():
                if k not in cols:
                    cols.append(k)
        return cols

    def _records_table(
        self, label: str, records: List[Dict[str, Any]],
        columns: List[str], sources: List[str],
    ) -> Optional[Dict[str, Any]]:
        """A list of record dicts → {caption, columns, rows}. Every column and
        row is rendered; the fixed-layout `.tbl` CSS wraps wide content so it
        cannot overflow the page."""
        if not columns:
            return None

        from functionalities.report_generation.display_utils import humanize_field_name
        source_str = " · ".join(sources) if sources else ""
        rows = []
        for rec in records:
            row = [self._cell(rec.get(c)) for c in columns]
            if source_str:
                row.append(source_str)
            rows.append(row)

        header = [humanize_field_name(c) for c in columns]
        # source_col flags the appended Source column so the template links its
        # cells (src_chips) instead of rendering them as plain text.
        source_col = len(header) if source_str else None
        if source_str:
            header.append("Source")
        return {"caption": label, "columns": header, "rows": rows,
                "source_col": source_col}

    @staticmethod
    def _cell(value: Any) -> str:
        """Render a single table cell value compactly."""
        if value is None or value == "":
            return "—"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value if v) or "—"
        if isinstance(value, dict):
            return ", ".join(f"{k}: {v}" for k, v in value.items() if v) or "—"
        return str(value).strip() or "—"

    @staticmethod
    def _best_entry(entries: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
        """Pick the most-agreed entry (consensus > single > minority > first)."""
        if not entries:
            return None
        return next(
            (e for e in entries if e.get('agreement') in ('consensus', 'single')),
            entries[0],
        )

    @staticmethod
    def _is_scalar(value: Any) -> bool:
        return isinstance(value, (str, bool, int, float)) and not isinstance(value, list)

    @staticmethod
    def _scalar_str(value: Any) -> str:
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value).strip()

    # =====================================================================
    # EXTERNAL IDENTIFIERS  (from raw data_metadata, not the cleaned stream)
    # =====================================================================
    def build_external_ids(
        self, universal_id: str, cache_dir: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Build a mono code-chip cloud of database identifiers (e.g. EASIN
        R12250) from the species' raw `data_metadata` file. Returns None when no
        identifiers are present. `cache_dir` is for offline tests; production
        leaves it None so the session-aware default resolves it."""
        if not universal_id:
            return None
        try:
            from core.cache_layer.categorized_data_helpers import load_category_file
            meta = load_category_file(universal_id, 'data_metadata', cache_dir)
        except Exception as e:
            print(f"WARNING ReportDataBuilder: external IDs load failed: {e}")
            return None
        if not isinstance(meta, dict):
            return None

        # One identifier per issuing database. When the same ID type appears in
        # several blocks with different values (e.g. an AphiaID in both the
        # AquaNIS and WRiMS blocks), prefer the block whose source owns that DB.
        by_db: Dict[str, tuple] = {}  # db -> (value, aligned)

        def _add(db: str, value: Any, source: str) -> None:
            if value in (None, '', [], {}):
                return
            aligned = (source or '').upper().replace('WRIMS', 'WORMS') == db.upper()
            cur = by_db.get(db)
            if cur is None or (aligned and not cur[1]):
                by_db[db] = (str(value).strip(), aligned)

        # Top-level scalar identifier fields (e.g. easin_id → "EASIN R12250").
        for field, entries in meta.items():
            db = _EXTERNAL_ID_LABELS.get(field.lower())
            if db and isinstance(entries, list) and entries:
                _add(db, entries[0].get('value'), entries[0].get('source', ''))

        # Nested identifier dicts: data_metadata aggregates several per-source
        # metadata blocks whose value dicts carry the real IDs (gbif_key,
        # aphia_id, tsn, ncbi, …) that the top-level scan never sees.
        for field in _NESTED_ID_FIELDS:
            for entry in meta.get(field, []) or []:
                value = entry.get('value') if isinstance(entry, dict) else None
                if not isinstance(value, dict):
                    continue
                source = entry.get('source', '')
                for k, v in value.items():
                    db = _EXTERNAL_ID_LABELS.get(str(k).lower())
                    if db:
                        _add(db, v, source)

        if not by_db:
            return None
        items = [{"text": f"{db} {val}"} for db, (val, _) in by_db.items()]
        return {"label": "External identifiers", "code": True, "items": items}

    # =====================================================================
    # RESEARCH EVIDENCE  (raw is_research_data entries → quoted extracts)
    # =====================================================================
    def build_evidence(
        self, universal_id: str, category: str, cache_dir: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """Return research extracts for one category as
        [{quote, source, verdict?, confidence?}], read from the raw category file
        (the cleaned stream discards is_research_data + verification metadata).
        Deduped by (quote, source). `cache_dir` is for offline tests."""
        if not universal_id or not category:
            return []
        try:
            from core.cache_layer.categorized_data_helpers import load_category_file
            fields = load_category_file(universal_id, category, cache_dir)
        except Exception as e:
            print(f"WARNING ReportDataBuilder: evidence load failed for {category}: {e}")
            return []
        if not isinstance(fields, dict):
            return []

        out: List[Dict[str, Any]] = []
        seen: set = set()
        for entries in fields.values():
            if not isinstance(entries, list):
                continue
            for e in entries:
                if not isinstance(e, dict) or not e.get('is_research_data'):
                    continue
                quote = (e.get('source_quote') or e.get('value') or '')
                quote = ' '.join(str(quote).split()).strip()
                source = (e.get('source') or 'Research Source').strip()
                if not quote or source in _INTERNAL_LABELS:
                    continue
                key = (quote.lower(), source.lower())
                if key in seen:
                    continue
                seen.add(key)
                item: Dict[str, Any] = {"quote": quote, "source": source}
                if e.get('verification_verdict'):
                    item["verdict"] = e['verification_verdict']
                if e.get('verification_confidence'):
                    item["confidence"] = e['verification_confidence']
                out.append(item)
        return out

    # =====================================================================
    # REFERENCES
    # =====================================================================
    def build_references(
        self, species_name: str, universal_id: str, sources: List[str],
        reference_style: str = "numbered",
    ) -> List[Dict[str, str]]:
        """Return an ordered [{citation, link}] list for the references block.

        Databases first, then research publications. "numbered" keeps source
        order of appearance; "apa" sorts alphabetically. The template numbers
        the list itself, so no [N] prefix is emitted here.
        """
        from core.dashboard.dashboard_tools import get_all_database_links_with_species

        if not sources:
            return []

        try:
            database_links = get_all_database_links_with_species(universal_id)
        except Exception:
            database_links = []

        # Keep EVERY link per database (one per synonym/name variant searched —
        # same data the dashboard's search overview shows), not just the first.
        # db_url_map keeps the primary (accepted-taxon) URL for the citation line;
        # db_links_map keeps the full deduped list for the bibliography entry.
        db_url_map: Dict[str, str] = {}
        db_links_map: Dict[str, List[Dict[str, str]]] = {}
        for link in database_links:
            db_name = link['database']
            keys = ['WRiMS', 'WoRMS'] if db_name == 'WRiMS' else [db_name]
            variant = {'name': link['species_name'], 'url': link['url']}
            if link.get('introduced_url'):
                variant['introduced_url'] = link['introduced_url']
            for k in keys:
                db_url_map.setdefault(k, link['url'])
                lst = db_links_map.setdefault(k, [])
                if not any(x['url'] == link['url'] for x in lst):
                    lst.append(variant)

        sources_meta = self._load_sources_metadata(universal_id)
        title_to_citation: Dict[str, Dict[str, Any]] = {
            meta.get('title', '').strip().lower(): meta
            for meta in sources_meta.values()
            if meta.get('title')
        }
        translated_titles = self._get_translated_source_titles(universal_id)

        all_db_keys = set(_DB_FULL_NAMES.keys())
        visible_sources = [s for s in sources if s not in _INTERNAL_LABELS]

        db_sources = [s for s in visible_sources if s in all_db_keys]
        research_sources: List[tuple] = []
        seen_citation_titles: set = set()
        for s in visible_sources:
            if s in all_db_keys or s in _INTERNAL_LABELS:
                continue
            citation = title_to_citation.get(s.strip().lower())
            if citation:
                norm_title = (citation.get('title') or '').strip().lower()
                if norm_title and norm_title in seen_citation_titles:
                    continue
                if norm_title:
                    seen_citation_titles.add(norm_title)
            s_stripped = re.sub(r'\s*\(AI-extracted data\)\s*$', '', s).strip()
            if not citation and (s_stripped.startswith('manual_upload://') or s_stripped.endswith('.pdf')):
                clean = s_stripped.replace('manual_upload://', '').removesuffix('.pdf').replace('_', ' ').replace('-', ' ')
                if clean.strip().lower() in seen_citation_titles:
                    continue
                research_sources.append((s, clean, None))
            else:
                research_sources.append((s, s, citation))

        # APA and Harvard both sort references alphabetically by first author.
        # Numbered and Vancouver superscript keep appearance order.
        if reference_style in ("apa", "harvard"):
            db_order = sorted(db_sources)

            def _sort_key(item):
                _, display_name, cit = item
                if cit:
                    authors = cit.get('authors') or []
                    if authors:
                        return authors[0].split(',')[0].strip().lower()
                    return (cit.get('title') or '').lower()
                return display_name.lower()
            research_order = sorted(research_sources, key=_sort_key)
        else:
            # "numbered" and "vancouver_superscript" — keep appearance order.
            db_order = db_sources
            research_order = research_sources

        refs: List[Dict[str, str]] = []
        for source_name in db_order:
            full_name = _DB_FULL_NAMES.get(source_name, source_name)
            url = db_url_map.get(source_name)
            ref = self._to_ref(self._format_apa_database_entry(source_name, full_name, url))
            ref['key'] = source_name  # join handle: matches a fact's sources[*]
            # all per-variant links (synonyms) for this database, for the bibliography
            ref['variant_links'] = db_links_map.get(source_name, [])
            refs.append(ref)

        for original_key, display_name, citation in research_order:
            entry = self._format_apa_research_entry(citation) if citation else display_name
            ref = self._to_ref(entry)
            tag = self._translation_tag(display_name, translated_titles)
            if tag:
                ref['citation'] += tag.replace('*', '')
            ref['key'] = original_key
            refs.append(ref)

        return refs

    @staticmethod
    def _to_ref(formatted: str) -> Dict[str, str]:
        """Split a formatted citation string into {citation, link}, stripping
        markdown emphasis and peeling off a trailing URL/DOI as the link."""
        text = formatted.replace('*', '')
        link = ''
        m = re.search(r'(https?://\S+)\s*$', text)
        if m:
            link = m.group(1)
            text = text[:m.start()].rstrip()
        return {"citation": text.strip(), "link": link}

    # =====================================================================
    # PRESERVED LOOKUPS / FORMATTERS  (verbatim from the former formatter)
    # =====================================================================
    def _get_translated_source_titles(self, universal_id: str) -> Dict[str, str]:
        """Returns {source_title: translated_from_language} for translated sources."""
        import json
        from core.utils.cache_manager import get_extracted_data_dir

        result = {}
        try:
            extracted_dir = get_extracted_data_dir()
            species_dir = extracted_dir / universal_id
            if not species_dir.exists():
                return result
            for json_file in species_dir.rglob("*.json"):
                try:
                    with open(json_file, encoding="utf-8") as f:
                        data = json.load(f)
                    meta = data.get("metadata", {})
                    translated_from = meta.get("translated_from")
                    source_title = meta.get("source_title", "")
                    if translated_from and source_title and source_title not in result:
                        result[source_title] = translated_from
                except Exception:
                    continue
        except Exception:
            pass
        return result

    def _humanize_category_name(self, category_name: str) -> str:
        """Convert raw category name to human-readable title via the registry."""
        from core.registries.topic_registry import StandardTopicRegistry
        topic = StandardTopicRegistry.get_topic(category_name)
        if topic:
            return topic.display_name
        return category_name.replace('_', ' ').title()

    def _load_sources_metadata(self, universal_id: str) -> Dict[str, Any]:
        """Load sources_metadata.json for a species, or {} if absent."""
        import json
        from core.utils.cache_manager import get_extracted_data_dir
        try:
            extracted_dir = get_extracted_data_dir()
            metadata_path = extracted_dir / universal_id / "sources_metadata.json"
            if not metadata_path.exists():
                return {}
            with open(metadata_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"WARNING ReportDataBuilder: Could not load sources_metadata.json: {e}")
            return {}

    def _format_apa_authors(self, authors: List[str]) -> str:
        """Format an author list into APA style."""
        if not authors:
            return ""
        if len(authors) > 6:
            listed = authors[:6]
            author_str = ", ".join(listed) + ", ... et al."
        elif len(authors) == 1:
            author_str = authors[0]
        else:
            author_str = ", ".join(authors[:-1]) + ", & " + authors[-1]
        return author_str

    def _format_apa_database_entry(
        self, source_name: str, full_name: str, url: Optional[str]
    ) -> str:
        year = datetime.now().year
        line = f"{source_name}. ({year}). *{full_name}* [Database]."
        if url:
            line += f" {url}"
        return line

    def _format_apa_research_entry(self, citation: Dict[str, Any]) -> str:
        parts = []
        author_str = self._format_apa_authors(citation.get('authors') or [])
        if author_str:
            parts.append(author_str + ".")
        year = citation.get('publication_year')
        parts.append(f"({year})." if year else "(n.d.).")
        title = (citation.get('title') or '').strip()
        if title:
            parts.append(f"{title}.")
        journal = (citation.get('journal_name') or '').strip()
        if journal:
            parts.append(f"*{journal}*.")
        doi = (citation.get('doi') or '').strip()
        url = (citation.get('url') or '').strip()
        if doi:
            parts.append(f"https://doi.org/{doi}")
        elif url:
            parts.append(url)
        return " ".join(parts)

    def _translation_tag(self, source_name: str, translated_titles: Dict[str, str]) -> str:
        for title, lang in translated_titles.items():
            if title[:40].lower() in source_name.lower():
                return f" *(translated from {lang})*"
        return ""
