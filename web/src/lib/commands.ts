export type CommandSection =
  | "Navigation"
  | "Stream"
  | "Macros"
  | "Admin"
  | "Tick"
  | "Theme"
  | "Misc";

export type Command = {
  id: string;
  label: string;
  hint?: string;
  section: CommandSection;
  action: () => void | Promise<void>;
};

export function fuzzyScore(query: string, label: string): number {
  if (!query) return 1;
  const q = query.toLowerCase();
  const l = label.toLowerCase();
  let qi = 0;
  let score = 0;
  let prev = " ";
  for (let li = 0; li < l.length && qi < q.length; li++) {
    const lc = l.charAt(li);
    const qc = q.charAt(qi);
    if (lc === qc) {
      score += 1;
      if (prev === " " || prev === "_") score += 2;
      qi++;
    }
    prev = lc;
  }
  return qi === q.length ? score : 0;
}

export function fuzzyFilter(query: string, commands: Command[]): Command[] {
  const sectionOrder: CommandSection[] = [];
  const buckets = new Map<CommandSection, { cmd: Command; score: number; idx: number }[]>();
  commands.forEach((cmd, idx) => {
    const score = fuzzyScore(query, cmd.label);
    if (score <= 0) return;
    let bucket = buckets.get(cmd.section);
    if (!bucket) {
      bucket = [];
      buckets.set(cmd.section, bucket);
      sectionOrder.push(cmd.section);
    }
    bucket.push({ cmd, score, idx });
  });
  const out: Command[] = [];
  for (const sec of sectionOrder) {
    const bucket = buckets.get(sec);
    if (!bucket) continue;
    bucket.sort((a, b) => b.score - a.score || a.idx - b.idx);
    for (const entry of bucket) out.push(entry.cmd);
  }
  return out;
}
