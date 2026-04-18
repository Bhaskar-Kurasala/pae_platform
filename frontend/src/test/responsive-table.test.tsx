import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ResponsiveTable } from "@/components/ui/responsive-table";

interface Row {
  id: string;
  name: string;
  score: number;
}

const COLUMNS = [
  { key: "name", header: "Name", cell: (r: Row) => r.name, primary: true },
  { key: "score", header: "Score", cell: (r: Row) => r.score.toString() },
];

const DATA: Row[] = [
  { id: "1", name: "Ada", score: 98 },
  { id: "2", name: "Grace", score: 100 },
];

describe("ResponsiveTable", () => {
  it("renders rows with headers in both layouts", () => {
    render(<ResponsiveTable columns={COLUMNS} data={DATA} rowKey={(r) => r.id} />);
    expect(screen.getAllByText("Ada").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Grace").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/score/i).length).toBeGreaterThan(0);
  });

  it("shows empty-state text when data is empty", () => {
    render(
      <ResponsiveTable
        columns={COLUMNS}
        data={[]}
        rowKey={(r) => r.id}
        emptyMessage="Nothing to show yet."
      />,
    );
    expect(screen.getByText(/nothing to show yet/i)).toBeInTheDocument();
  });

  it("calls onRowClick on mobile card activation", () => {
    const onRowClick = vi.fn();
    render(
      <ResponsiveTable
        columns={COLUMNS}
        data={DATA}
        rowKey={(r) => r.id}
        onRowClick={onRowClick}
      />,
    );
    const cards = screen.getAllByRole("button");
    fireEvent.click(cards[0]);
    expect(onRowClick).toHaveBeenCalledWith(DATA[0]);
  });
});
