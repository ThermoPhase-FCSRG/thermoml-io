# Scientific data model

ThermoML is hierarchical. A citation describes a source publication;
compounds contain sample and purity metadata; each dataset defines components,
phases, properties, variables, and constraints; numeric records refer back to
those definitions.

```text
ThermoMLDocument
├── Citation
├── Compound[]
│   └── Sample[]
│       └── PurityAssessment[]
└── DataSet[]
    ├── PropertyDefinition[]
    ├── VariableDefinition[]
    ├── ConstraintDefinition[]
    └── DataPoint[]
        ├── variable_values[]
        └── property_values[]
```

## Numeric fidelity

Reported values are parsed as `Decimal`. XML inputs retain their original
numeric text and reported significant-digit count. Official NIST JSON numbers
are loaded directly as `Decimal`, without a binary floating-point round trip,
but JSON may not preserve the exact lexical decimal spelling of the related
XML. Every JSON-parsed document carries this warning explicitly.

`SourceProvenance` identifies the exact serialization parsed. If paired JSON
recovers a malformed XML, `SourceRecovery` additionally preserves the failed
XML locator, SHA-256, media type, exception type, and exception message.
This XML-first behavior is shared by official URL loading and bulk-archive
traversal and can be disabled with `json_fallback="never"`.

## Chemical identity

`nOrgNum` and `nCompIndex` are local references. They are never used as global
system identifiers. A stable system key is built from reported InChIKeys,
standard InChI, CAS numbers, or names, in that preference order.

`Compound` preserves reported common names, IUPAC name, CAS name, molecular
formula, standard InChI, InChIKey, CAS Registry Number, and sample metadata.
`ComponentIdentity` is a separate aggregate used for search. This separation
ensures that aliases learned from another document or from an explicit PubChem
request never overwrite the original publication metadata.

`ComponentIndex` joins records through shared strong identifiers. Weak aliases
are attached to a strong identity only when that association is unique across
the indexed source. Names and formulas alone never merge distinct
strong-identifier groups, so those queries produce an explicit ambiguity
error.

## Uncertainty

The model retains standard and expanded uncertainty, asymmetric bounds,
coverage factor, confidence level, evaluator, and evaluation method. Numeric
uncertainty entries in `NumValues` are linked to their definition-level
assessment metadata.

## Missing metadata

Most ThermoML metadata is optional. Absence means “not represented in this
document”; it must not be interpreted as zero uncertainty, perfect purity, or
an unspecified phase chosen by the parser.
