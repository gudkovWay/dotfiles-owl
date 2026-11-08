import { lstat, realpath, readFile, readdir, mkdir, writeFile, unlink } from "node:fs/promises";
import { resolve, join, relative, dirname } from "node:path";
import { safeRelative } from "./model";

export class Files {
  readonly changed = new Set<string>();
  constructor(readonly root: string, private scope?: string[]) {}
  private async path(file: string, readOnly = false): Promise<string> {
    const plan = readOnly && /^\.superpowers\/(?:plans|specs)\/.+/.test(file) && safeRelative(file.replace(/^\.superpowers\/(?:plans|specs)\//, ""));
    if (!safeRelative(file) && !plan) throw Error(`Unsafe repository path: ${file}`);
    const root = await realpath(this.root);
    let current = root;
    for (const part of file.split("/")) {
      current = join(current, part);
      try { if ((await lstat(current)).isSymbolicLink()) throw Error(`Refusing symlink: ${file}`); }
      catch (error) { if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) throw error; }
    }
    if (relative(root, current).startsWith("..")) throw Error("Path escaped worktree");
    return current;
  }
  async read(file: string): Promise<string> {
    const path = await this.path(file, true);
    if ((await lstat(path)).size > 256 * 1024) throw Error("File exceeds 256 KiB; choose a smaller source file");
    const text = await readFile(path, "utf8");
    if (text.includes("\0")) throw Error("Binary file is not supported");
    return text;
  }
  async list(directory = "", search?: string): Promise<string[]> {
    const start = directory ? await this.path(directory, true) : await realpath(this.root);
    const result: string[] = [];
    let visited = 0;
    const walk = async (path: string): Promise<void> => {
      for (const entry of await readdir(path, { withFileTypes: true })) {
        if (++visited > 6000 || result.length >= 100) return;
        const absolute = join(path, entry.name), file = relative(resolve(this.root), absolute);
        if (!safeRelative(file) || entry.isSymbolicLink() || /^(dist|build|coverage|\.nuxt|\.output|vendor)$/.test(entry.name)) continue;
        if (entry.isDirectory()) await walk(absolute);
        else if (entry.isFile()) {
          if (search === undefined) result.push(file);
          else {
            try {
              const text = await this.read(file);
              text.split("\n").forEach((line, index) => { if (result.length < 100 && line.includes(search)) result.push(`${file}:${index + 1}:${line.slice(0, 240)}`); });
            } catch { /* Skip oversized/binary/unreadable files in bounded search. */ }
          }
        }
      }
    };
    await walk(start);
    return result;
  }
  async change(file: string, action: "create" | "replace" | "delete", before: string, after: string, signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    if (!this.scope?.includes(file)) throw Error(`File outside approved write scope: ${file}`);
    const path = await this.path(file);
    if (action === "create") {
      await mkdir(dirname(path), { recursive: true });
      signal?.throwIfAborted();
      await writeFile(path, after, { flag: "wx" });
    } else {
      const current = await this.read(file);
      if (!before || !current.includes(before) || current.indexOf(before) !== current.lastIndexOf(before)) throw Error("Expected text must match a unique existing block");
      signal?.throwIfAborted();
      if (action === "delete") {
        if (current !== before) throw Error("Deletion requires the entire current file as expected text");
        await unlink(path);
      } else await writeFile(path, current.replace(before, () => after));
    }
    this.changed.add(file);
  }
}
