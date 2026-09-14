/** Field Mapper expression helpers — honest list of what eval_expr supports today. */

export type MapperFnGroup = {
  id: string;
  label: string;
  items: { sig: string; tip: string }[];
};

export const MAPPER_FUNCTION_GROUPS: MapperFnGroup[] = [
  {
    id: "string",
    label: "String",
    items: [
      { sig: "upper(x)", tip: "Uppercase" },
      { sig: "lower(x)", tip: "Lowercase" },
      { sig: "str(x)", tip: "To string" },
      { sig: "len(x)", tip: "Length" },
      { sig: "a + b", tip: "Concatenate / add" },
      { sig: 'col("Name")', tip: "Column with spaces / case" },
    ],
  },
  {
    id: "math",
    label: "Math",
    items: [
      { sig: "int(x)", tip: "To integer" },
      { sig: "float(x)", tip: "To float" },
      { sig: "abs(x)", tip: "Absolute value" },
      { sig: "round(x[, n])", tip: "Round" },
      { sig: "min(a, b)", tip: "Minimum" },
      { sig: "max(a, b)", tip: "Maximum" },
      { sig: "a * b / c", tip: "Arithmetic" },
    ],
  },
  {
    id: "null",
    label: "Null / empty",
    items: [
      { sig: "coalesce(a, b, …)", tip: "First non-null / non-empty" },
      { sig: "x == None", tip: "Null check" },
      { sig: 'x == ""', tip: "Empty string" },
    ],
  },
  {
    id: "date",
    label: "Date / time",
    items: [
      {
        sig: "str(x)",
        tip: "DEMO: treat dates as strings today — dedicated parse/format helpers planned",
      },
      {
        sig: "int(x)",
        tip: "DEMO: numeric epoch-style values only when already numeric",
      },
    ],
  },
];
