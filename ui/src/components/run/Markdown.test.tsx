import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Markdown, parseMarkdown } from "./Markdown";

const NOTES = `# Migration Review Notes

- Status: running
- Generated HCL files: 12

## Validation Result
{
  "passed": true,
  "terraform_validate_passed": true
}

## Next Actions
1. Review quarantine_report.json for blocked resources.
2. Validate generated HCL with \`terraform validate\` before **apply**.
`;

describe("parseMarkdown", () => {
  it("splits headings, lists, JSON blocks and paragraphs", () => {
    const blocks = parseMarkdown(NOTES);
    expect(blocks.map((block) => block.kind)).toEqual(["heading", "list", "heading", "code", "heading", "list"]);
    expect(blocks[1]).toMatchObject({ kind: "list", ordered: false, items: ["Status: running", "Generated HCL files: 12"] });
    expect(blocks[3]).toMatchObject({ kind: "code", text: '{\n  "passed": true,\n  "terraform_validate_passed": true\n}' });
    expect(blocks[5]).toMatchObject({ kind: "list", ordered: true });
  });

  it("joins wrapped paragraph lines and handles fenced code", () => {
    const blocks = parseMarkdown("first line\nsecond line\n\n```\nraw {\n```\n");
    expect(blocks).toEqual([
      { kind: "paragraph", text: "first line second line" },
      { kind: "code", text: "raw {" },
    ]);
  });
});

describe("Markdown", () => {
  it("renders inline code and bold but leaves identifiers with underscores alone", () => {
    render(<Markdown source="Check `validation_result` and **apply** the fix to terraform_validate_passed." />);
    expect(screen.getByText("validation_result").tagName).toBe("CODE");
    expect(screen.getByText("apply").tagName).toBe("STRONG");
    expect(screen.getByText(/terraform_validate_passed/)).toBeInTheDocument();
    expect(document.querySelector("em")).toBeNull();
  });
});
