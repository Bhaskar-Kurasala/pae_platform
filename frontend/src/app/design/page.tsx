"use client";

import * as React from "react";
import {
  AlertCircle,
  Bookmark,
  Check,
  Command,
  Download,
  Info,
  Plus,
  Rocket,
  Search,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { EmptyState } from "@/components/ui/empty-state";
import { Badge, StatusDot } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipProvider } from "@/components/ui/tooltip";
import { Popover } from "@/components/ui/popover";
import { Avatar, AvatarFallback, AvatarGroup, avatarColor, toInitials } from "@/components/ui/avatar";
import { Kbd } from "@/components/ui/kbd";
import { Combobox, type ComboboxItem } from "@/components/ui/combobox";
import { ResponsiveDialog } from "@/components/ui/responsive-dialog";
import { CommandPalette, type CommandItem } from "@/components/ui/command-palette";
import { CodeBlock } from "@/components/ui/code-block";
import { DataTable, type ColumnDef } from "@/components/ui/data-table";
import { Icon } from "@/components/ui/icon";
import { toast } from "@/lib/toast";
import { SlideIn, Stagger, StaggerItem } from "@/components/ui/motion";

/**
 * /design — live gallery of every UI primitive.
 *
 * This route replaces a formal Storybook install for Phase 0.5. Every
 * primitive appears here in its key variant/state combinations so design
 * regressions are immediately visible during `pnpm dev`.
 */

type Row = { id: string; name: string; role: string; status: "active" | "invited" | "paused"; joined: string };

const tableData: Row[] = [
  { id: "1", name: "Ada Lovelace", role: "Founder", status: "active", joined: "2026-03-02" },
  { id: "2", name: "Grace Hopper", role: "Engineer", status: "active", joined: "2026-03-09" },
  { id: "3", name: "Alan Turing", role: "Researcher", status: "invited", joined: "2026-03-14" },
  { id: "4", name: "Margaret Hamilton", role: "Engineer", status: "active", joined: "2026-03-20" },
  { id: "5", name: "Katherine Johnson", role: "Analyst", status: "paused", joined: "2026-04-01" },
  { id: "6", name: "Dennis Ritchie", role: "Engineer", status: "active", joined: "2026-04-05" },
  { id: "7", name: "Barbara Liskov", role: "Researcher", status: "active", joined: "2026-04-09" },
];

const tableColumns: ColumnDef<Row>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "role", header: "Role" },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => {
      const v = row.original.status;
      const tone = v === "active" ? "success" : v === "invited" ? "info" : "warning";
      return <Badge variant={tone}>{v}</Badge>;
    },
  },
  { accessorKey: "joined", header: "Joined" },
];

const comboItems: ComboboxItem[] = [
  { value: "py", label: "Python", group: "Runtimes" },
  { value: "ts", label: "TypeScript", group: "Runtimes" },
  { value: "go", label: "Go", group: "Runtimes" },
  { value: "rs", label: "Rust", group: "Runtimes" },
  { value: "pg", label: "PostgreSQL", group: "Databases" },
  { value: "rd", label: "Redis", group: "Databases" },
];

const SAMPLE_CODE = `from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health() -> dict[str, str]:
    # Production check — hits DB + cache
    return {"status": "ok"}
`;

export default function DesignPage() {
  const [text, setText] = React.useState("");
  const [combo, setCombo] = React.useState<ComboboxItem | null>(null);
  const [multi, setMulti] = React.useState<ComboboxItem[]>([]);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const [palette, setPalette] = React.useState(false);

  const paletteItems: CommandItem[] = [
    {
      id: "new",
      label: "New lesson",
      icon: <Plus className="h-4 w-4" />,
      shortcut: "mod+n",
      group: "Create",
      onSelect: () => toast.success("Created a new lesson"),
    },
    {
      id: "search",
      label: "Search docs",
      icon: <Search className="h-4 w-4" />,
      group: "Navigate",
      onSelect: () => toast.info("Opened search"),
    },
    {
      id: "bookmark",
      label: "Bookmark page",
      icon: <Bookmark className="h-4 w-4" />,
      group: "Navigate",
      onSelect: () => toast.message("Bookmarked"),
    },
    {
      id: "launch",
      label: "Launch rocket",
      icon: <Rocket className="h-4 w-4" />,
      shortcut: "mod+shift+l",
      group: "Actions",
      onSelect: () => toast.success("Rocket launched"),
    },
  ];

  return (
    <TooltipProvider>
      <main className="mx-auto max-w-5xl px-6 py-10 space-y-16">
        <header>
          <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
            Phase 0.5 · Design Gallery
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">UI primitives</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Live inventory of every component in <code>components/ui/*</code>. Regressions are
            visible at a glance.
          </p>
        </header>

        <Section title="Buttons" id="buttons">
          <Row2>
            <Button>Default</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="destructive">Destructive</Button>
            <Button variant="link">Link</Button>
          </Row2>
          <Row2>
            <Button size="sm">Small</Button>
            <Button>Medium</Button>
            <Button size="lg">Large</Button>
            <Button size="icon" aria-label="Add">
              <Plus />
            </Button>
          </Row2>
          <Row2>
            <Button loading>Saving…</Button>
            <Button success>Saved</Button>
            <Button iconStart={<Download />}>Download</Button>
            <Button iconEnd={<Check />} variant="outline">
              Confirm
            </Button>
            <Button disabled>Disabled</Button>
          </Row2>
        </Section>

        <Section title="Inputs & Textarea" id="inputs">
          <Row2>
            <Input placeholder="Default" />
            <Input placeholder="With leading icon" leadingIcon={<Search />} />
            <Input placeholder="Clearable" clearable defaultValue="hello" />
            <Input placeholder="Invalid" invalid aria-invalid />
            <Input placeholder="Disabled" disabled />
          </Row2>
          <Textarea
            placeholder="Autosizing textarea with counter…"
            autosize
            maxRows={6}
            showCounter
            maxLength={200}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </Section>

        <Section title="Loaders" id="loaders">
          <Row2>
            <Spinner size="sm" />
            <Spinner />
            <Spinner size="lg" />
            <Spinner tone="muted" />
          </Row2>
          <div className="space-y-2">
            <Skeleton shape="title" />
            <Skeleton shape="text" lines={3} />
            <Row2>
              <Skeleton shape="avatar" />
              <Skeleton shape="button" />
              <Skeleton shape="chip" />
            </Row2>
            <Skeleton shape="card" />
          </div>
          <div className="space-y-3">
            <Progress value={35} />
            <Progress value={70} tone="success" />
            <Progress value={null} tone="warning" size="sm" />
            <Progress size="lg" tone="destructive" value={90} />
          </div>
        </Section>

        <Section title="Empty states" id="empty">
          <EmptyState
            icon={<AlertCircle />}
            title="No results yet"
            description="Try adjusting your search or clearing filters."
            action={<Button>Clear filters</Button>}
            bordered
          />
        </Section>

        <Section title="Badges" id="badges">
          <Row2>
            <Badge>Default</Badge>
            <Badge variant="secondary">Secondary</Badge>
            <Badge variant="outline">Outline</Badge>
            <Badge variant="destructive">Destructive</Badge>
            <Badge variant="success">Success</Badge>
            <Badge variant="warning">Warning</Badge>
            <Badge variant="info">Info</Badge>
          </Row2>
          <Row2>
            <StatusDot tone="success" pulse />
            <StatusDot tone="warning" />
            <StatusDot tone="destructive" />
            <StatusDot tone="info" />
          </Row2>
        </Section>

        <Section title="Cards" id="cards">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle>Default</CardTitle>
                <CardDescription>Static card</CardDescription>
              </CardHeader>
              <CardContent>Content lives here.</CardContent>
            </Card>
            <Card variant="interactive">
              <CardHeader>
                <CardTitle>Interactive</CardTitle>
                <CardDescription>Hover me</CardDescription>
              </CardHeader>
              <CardContent>Lifts on hover.</CardContent>
            </Card>
            <Card variant="elevated">
              <CardHeader>
                <CardTitle>Elevated</CardTitle>
                <CardDescription>Higher shadow</CardDescription>
              </CardHeader>
              <CardContent>Always elevated.</CardContent>
            </Card>
          </div>
        </Section>

        <Section title="Tabs" id="tabs">
          <Tabs defaultValue="overview" className="w-full">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="activity">Activity</TabsTrigger>
              <TabsTrigger value="settings">Settings</TabsTrigger>
            </TabsList>
            <TabsContent value="overview">Overview pane</TabsContent>
            <TabsContent value="activity">Activity pane</TabsContent>
            <TabsContent value="settings">Settings pane</TabsContent>
          </Tabs>
          <Tabs defaultValue="a" className="w-full">
            <TabsList variant="pill">
              <TabsTrigger value="a">Day</TabsTrigger>
              <TabsTrigger value="b">Week</TabsTrigger>
              <TabsTrigger value="c">Month</TabsTrigger>
            </TabsList>
            <TabsContent value="a">Day chart</TabsContent>
          </Tabs>
        </Section>

        <Section title="Tooltip & Popover" id="overlays">
          <Row2>
            <Tooltip content="Copy to clipboard" shortcut="mod+c">
              <Button variant="outline">Hover me</Button>
            </Tooltip>
            <Popover trigger={<Button variant="outline">Open popover</Button>}>
              <div className="space-y-2 p-1">
                <p className="text-sm font-medium">Quick actions</p>
                <p className="text-xs text-muted-foreground">
                  Popovers float over content with elevation-3 shadow.
                </p>
              </div>
            </Popover>
          </Row2>
        </Section>

        <Section title="Avatars" id="avatars">
          <Row2>
            {["Ada Lovelace", "grace.hopper@example.com", "Alan Turing"].map((n) => (
              <Avatar key={n}>
                <AvatarFallback className={avatarColor(n)}>{toInitials(n)}</AvatarFallback>
              </Avatar>
            ))}
            <Avatar size="lg">
              <AvatarFallback className={avatarColor("Margaret Hamilton")}>
                {toInitials("Margaret Hamilton")}
              </AvatarFallback>
            </Avatar>
            <Avatar size="xl">
              <AvatarFallback className={avatarColor("Katherine Johnson")}>
                {toInitials("Katherine Johnson")}
              </AvatarFallback>
            </Avatar>
          </Row2>
          <AvatarGroup>
            {["Ada", "Grace", "Alan", "Margaret"].map((n) => (
              <Avatar key={n}>
                <AvatarFallback className={avatarColor(n)}>{toInitials(n)}</AvatarFallback>
              </Avatar>
            ))}
          </AvatarGroup>
        </Section>

        <Section title="Kbd" id="kbd">
          <Row2>
            <Kbd keys="mod+k" />
            <Kbd keys="shift+enter" />
            <Kbd keys="esc" />
            <Kbd keys="up" />
            <Kbd keys="down" />
          </Row2>
        </Section>

        <Section title="Combobox" id="combobox">
          <div className="max-w-sm space-y-3">
            <Combobox
              items={comboItems}
              value={combo}
              onValueChange={setCombo}
              aria-label="Single"
              placeholder="Pick one"
            />
            <Combobox
              multiple
              items={comboItems}
              value={multi}
              onValueChange={setMulti}
              aria-label="Multi"
              placeholder="Pick many"
            />
          </div>
        </Section>

        <Section title="Responsive Dialog / Command Palette / Toasts" id="dialogs">
          <Row2>
            <Button onClick={() => setDialogOpen(true)}>Open dialog</Button>
            <Button variant="outline" onClick={() => setPalette(true)} iconStart={<Command />}>
              Command palette
            </Button>
            <Button variant="secondary" onClick={() => toast.success("Saved!")}>
              Success toast
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                toast.undo("Deleted 3 items.", () => toast.message("Restored"))
              }
              iconStart={<Trash2 />}
            >
              Delete + undo
            </Button>
            <Button variant="ghost" onClick={() => toast.error("Something went wrong")}>
              Error toast
            </Button>
          </Row2>

          <ResponsiveDialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <ResponsiveDialog.Content>
              <ResponsiveDialog.Header>
                <ResponsiveDialog.Title>Responsive dialog</ResponsiveDialog.Title>
                <ResponsiveDialog.Description>
                  Renders as a Dialog on ≥640px, Sheet below.
                </ResponsiveDialog.Description>
              </ResponsiveDialog.Header>
              <div className="p-4 text-sm text-muted-foreground">
                Body goes here. Try resizing the window.
              </div>
              <ResponsiveDialog.Footer>
                <Button variant="outline" onClick={() => setDialogOpen(false)}>
                  Cancel
                </Button>
                <Button onClick={() => setDialogOpen(false)}>Confirm</Button>
              </ResponsiveDialog.Footer>
            </ResponsiveDialog.Content>
          </ResponsiveDialog>

          <CommandPalette
            open={palette}
            onOpenChange={setPalette}
            items={paletteItems}
            triggerShortcut={null}
          />
        </Section>

        <Section title="Code block" id="code">
          <CodeBlock code={SAMPLE_CODE} language="python" filename="app/main.py" />
          <CodeBlock
            code={SAMPLE_CODE}
            language="python"
            filename="highlighted.py"
            highlightLines={[5, 6]}
          />
        </Section>

        <Section title="DataTable" id="table">
          <DataTable
            columns={tableColumns}
            data={tableData}
            searchPlaceholder="Search members…"
            initialPageSize={5}
            pageSizeOptions={[5, 10, 25]}
          />
        </Section>

        <Section title="Motion" id="motion">
          <SlideIn direction="left">
            <div className="rounded-lg border border-foreground/10 bg-card p-4 text-sm">
              Slides in from the left.
            </div>
          </SlideIn>
          <Stagger as="ul" className="space-y-2">
            {["Alpha", "Beta", "Gamma", "Delta"].map((n) => (
              <StaggerItem key={n}>
                <li className="rounded-lg border border-foreground/10 bg-card px-3 py-2 text-sm">
                  {n}
                </li>
              </StaggerItem>
            ))}
          </Stagger>
        </Section>

        <Section title="Icon registry" id="icons">
          <Row2>
            <Icon name="intent-skill" />
            <Icon name="intent-skill" size="lg" />
            <Icon name="intent-skill" size="xl" bold />
            <Info className="h-4 w-4 text-muted-foreground" />
          </Row2>
        </Section>
      </main>
    </TooltipProvider>
  );
}

function Section({
  title,
  id,
  children,
}: {
  title: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="space-y-4">
      <div className="flex items-baseline justify-between border-b border-foreground/10 pb-2">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        <a
          href={`#${id}`}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          #{id}
        </a>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function Row2({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-3">{children}</div>;
}
