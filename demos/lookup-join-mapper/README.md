# Two sources → Lookup Join → Field Mapper → CSV

Demonstrates:

1. **Two sources** wired into **Lookup Join** — primary (`orders`) → left/`in` handle, lookup (`customers`) → `right` handle
2. Join types / match mode in node config (`how`, `match`)
3. **Field Mapper** with a **Variables** middle layer (`full_name`, `total`) before output mappings

```bash
make seed
FORMULAETL_DEMO=1 FORMULAETL_WORK_DIR=. python3 -m formulaetl.cli run demos/lookup-join-mapper/pipeline.json
```

Output: `data/out/lookup_join_mapper.csv`
