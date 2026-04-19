import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Briefcase, FileText, MessageCircle } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";

const CAREER_SECTIONS = [
  {
    title: "Resume Builder",
    description: "AI-generated summary based on your skill profile.",
    href: "/career/resume",
    icon: FileText,
  },
  {
    title: "Interview Prep",
    description: "Searchable bank of technical and behavioural questions.",
    href: "/career/interview-bank",
    icon: MessageCircle,
  },
  {
    title: "JD Fit Analysis",
    description: "Paste a job description to get your fit score and gap plan.",
    href: "/career/jd-fit",
    icon: Briefcase,
  },
] as const;

export default function CareerPage() {
  return (
    <div className="p-6">
      <PageHeader eyebrow="Career" title="Job Readiness" />
      <div className="grid gap-4 sm:grid-cols-3">
        {CAREER_SECTIONS.map(({ title, description, href, icon: Icon }) => (
          <Link key={href} href={href} aria-label={title}>
            <Card className="h-full transition-shadow hover:shadow-md">
              <CardHeader className="pb-2">
                <Icon className="mb-2 h-5 w-5 text-primary" aria-hidden="true" />
                <CardTitle className="text-base">{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{description}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
