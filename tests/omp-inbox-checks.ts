import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, readFile, symlink, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Inbox, decisionSchema, independent, shouldCapture, type Host, type Item, type Decision, type State } from "../omp/extensions/inbox/model";
import { Files } from "../omp/extensions/inbox/files";

const fix: Decision = { kind: "fix", report: "Independent typo; no shared contract", files: ["src/other.ts"], contracts: [], dependsOnMain: false };
const snapshot = {
  cwd: "/repo", context: "approved feature plan", capturedAt: "2026-10-13T09:00:00.000Z",
  repo: { cwd: "/repo", branch: "feature", base: "origin/main", head: "abc", dirty: ["src/main.ts"], writes: ["src/main.ts"] },
};
assert.equal(shouldCapture(true, false, "main", "interactive", "fix"), true);
for (const text of ["/commit", "!pwd", "$x", "/inbox off"]) assert.equal(shouldCapture(true, false, "main", "interactive", text), false);
assert.equal(shouldCapture(false, false, "main", "interactive", "fix"), false);
assert.equal(shouldCapture(true, true, "main", "interactive", "fix"), false);
assert.equal(shouldCapture(true, false, "sub", "interactive", "fix"), false);
assert.equal(shouldCapture(true, false, "main", "extension", "fix"), false);
assert.throws(() => decisionSchema.parse({ kind: "fix", report: "trust me" }));
assert.equal(independent(decisionSchema.parse(fix), snapshot, []), true);
assert.equal(independent({ ...fix, contracts: ["src/main.ts"] }, snapshot, []), false);
assert.equal(independent({ ...fix, dependsOnMain: true }, snapshot, []), false);
assert.equal(independent({ ...fix, files: ["src/main.ts"] }, snapshot, []), false);
assert.equal(independent(decisionSchema.parse(fix), snapshot, ["src/other.ts"]), false);
assert.equal(independent(fix, { ...snapshot, repo: undefined }, []), false);
assert.equal(independent(fix, { ...snapshot, repo: { ...snapshot.repo, base: undefined } }, []), false);

let decision: Decision = { kind: "amendment", report: "Change approved plan", files: [], contracts: [], dependsOnMain: true };
let stop = 0, runs = 0;
const applied: Item[] = [], persisted: State[] = [];
const host: Host = {
  snapshot: async () => snapshot,
  triage: async () => decision,
  execute: async (_item, _snap, signal) => {
    runs++;
    const { promise, reject } = Promise.withResolvers<string>();
    signal.addEventListener("abort", () => reject(new Error("cancelled")), { once: true });
    return promise;
  },
  persist: state => persisted.push(structuredClone(state)),
  notify: () => {}, stop: () => { stop++; }, apply: item => { applied.push(item); }, idle: () => true,
};
const inbox = new Inbox(host);
assert.equal(inbox.enabled, true, "missing startup configuration must retain the existing ON default");
assert.equal(new Inbox(host, undefined, false).enabled, false, "a configured fresh session must start OFF");
assert.equal(new Inbox(host, { enabled: true, items: [] }, false).enabled, true, "saved ON must override a configured OFF default");
assert.equal(new Inbox(host, { enabled: false, items: [] }, true).enabled, false, "saved OFF must override a configured ON default");
const images: NonNullable<Item["images"]> = [{ type: "image", data: "base64", mimeType: "image/png" }];
const first = inbox.capture("also change plan", images);
assert.deepEqual(persisted[0].items[0].images, images);
await inbox.settleTriage();
assert.equal(first.status, "amendment");
inbox.apply(first.id, false);
assert.equal(applied[0].text, "also change plan");
assert.equal(first.status, "handed-off");
assert.throws(() => inbox.apply(first.id, false), /ready/);
assert.equal(applied.length, 1, "handoff must be exactly once");

decision = { ...fix, kind: "urgent", report: "Do not push" };
inbox.capture("wrong branch");
await inbox.settleTriage();
assert.equal(stop, 1);
decision = fix;
const worker = inbox.capture("independent fix");
await inbox.settleTriage();
assert.equal(runs, 1);
assert.equal(worker.status, "working");
decision = { ...fix, kind: "answer", report: "answer" };
const question = inbox.capture("what about this?");
await inbox.settleTriage();
assert.equal(question.status, "answered", "a worker must not block read-only triage");
inbox.mainMutation(["src/other.ts"]);
await inbox.settleWorkers();
assert.equal(worker.status, "failed");
assert.match(worker.report!, /conflict/);
assert.throws(() => inbox.apply(worker.id, true));

const interrupted = new Inbox(host, { enabled: true, items: [{ ...worker, status: "working" }] });
assert.equal(interrupted.items[0].status, "failed");
assert.match(interrupted.items[0].report!, /Interrupted/);
const failing = new Inbox({ ...host, triage: async () => { throw Error("provider unavailable"); } });
const saved = failing.capture("must not become steer", images);
await failing.settleTriage();
assert.equal(saved.status, "failed");
assert.equal(saved.text, "must not become steer");
assert.deepEqual(saved.images, images);
failing.apply(saved.id, false);
assert.equal(saved.status, "handed-off");
assert.equal(applied.at(-1)!.text, "must not become steer");
assert.deepEqual(applied.at(-1)!.images, images);
assert.throws(() => failing.apply(saved.id, false), /ready/);
const busy = new Inbox({ ...host, idle: () => false }, { enabled: true, items: [{ ...first, status: "amendment" }] });
assert.throws(() => busy.apply(first.id, false), /idle/);
assert.equal(independent(fix, { ...snapshot, repo: { ...snapshot.repo, writes: ["*"] } }, []), false);
const stoppedInput = inbox.capture("stop now", images, true);
assert.equal(stoppedInput.status, "urgent");
assert.equal(stop, 2);
const beforeFailure = new Inbox({ ...host, persist: () => { throw Error("disk unavailable"); } });
assert.throws(() => beforeFailure.capture("urgent stop", images, true), /disk/);
assert.equal(beforeFailure.items[0].status, "urgent", "persistence failure must not release a safety stop");
const withoutRepository = new Inbox({ ...host, snapshot: async () => ({ ...snapshot, repo: undefined }) });
decision = fix;
const heldWithoutRepository = withoutRepository.capture("no repository evidence", images);
await withoutRepository.settleTriage();
assert.equal(heldWithoutRepository.status, "amendment");
assert.equal(heldWithoutRepository.worktree, undefined);
const withoutBaseline = new Inbox({ ...host, snapshot: async () => ({ ...snapshot, repo: { ...snapshot.repo, base: undefined } }) });
const heldWithoutBaseline = withoutBaseline.capture("no stable baseline", images);
await withoutBaseline.settleTriage();
assert.equal(heldWithoutBaseline.status, "amendment");
assert.equal(heldWithoutBaseline.worktree, undefined);
const bound = new Inbox({
  ...host,
  execute: async (item, snap, signal) => {
    item.worktree = "/retained/bound-worktree";
    return host.execute(item, snap, signal);
  },
});
bound.bindRepository("/repo/main-worktree");
const boundItem = bound.capture("retain selected worktree", images);
assert.throws(() => bound.bindRepository("/another"), /active/);
await bound.settleTriage();
await bound.interrupt();
assert.equal(boundItem.repository, "/repo/main-worktree");
assert.throws(() => bound.apply(boundItem.id, false), /ready/);
bound.bindRepository("/another");
assert.equal(boundItem.repository, "/repo/main-worktree", "existing input must retain its original binding");
assert.equal(bound.repository, "/another");

decision = fix;
const transitioning = new Inbox({
  ...host,
  execute: async (item, _snapshot, signal) => {
    const { promise, resolve } = Promise.withResolvers<void>();
    signal.addEventListener("abort", () => { item.worktree = "/retained/partial-worktree"; resolve(); }, { once: true });
    await promise;
    signal.throwIfAborted();
    return "unreachable";
  },
});
const inFlight = transitioning.capture("fix interrupted during worktree setup", images);
await transitioning.settleTriage();
await transitioning.interrupt();
assert.equal(inFlight.status, "failed");
assert.equal(persisted.at(-1)!.items[0].worktree, "/retained/partial-worktree");
assert.throws(() => transitioning.retry(inFlight.id), /partial worktree/);

const root = await mkdtemp(join(tmpdir(), "omp-inbox-files-"));
try {
  await mkdir(join(root, "src"));
  await writeFile(join(root, "src/a.ts"), "one\none\n");
  const files = new Files(root, ["src/a.ts", "src/new.ts", "src/link.ts"]);
  await assert.rejects(files.change("src/a.ts", "replace", "one", "two"), /unique/);
  await files.change("src/a.ts", "replace", "one\none\n", "two\n");
  assert.equal(await readFile(join(root, "src/a.ts"), "utf8"), "two\n");
  await files.change("src/new.ts", "create", "", "new");
  await assert.rejects(files.change("src/new.ts", "create", "", "overwrite"));
  await assert.rejects(files.change("../escape", "create", "", "x"));
  await assert.rejects(files.change("src/not-approved.ts", "create", "", "x"), /scope/);
  await symlink("/tmp", join(root, "src/link.ts"));
  await assert.rejects(files.change("src/link.ts", "replace", "a", "b"), /symlink/);
  await assert.rejects(files.read("xd://tool"));
  await assert.rejects(files.read(".git/config"));
  await mkdir(join(root, ".superpowers/plans"), { recursive: true });
  await writeFile(join(root, ".superpowers/plans/approved.md"), "approved plan");
  assert.equal(await files.read(".superpowers/plans/approved.md"), "approved plan");
  await assert.rejects(files.change(".superpowers/plans/approved.md", "replace", "approved", "changed"), /scope/);
  const aborted = new AbortController(); aborted.abort();
  await assert.rejects(files.change("src/new.ts", "replace", "new", "bad", aborted.signal));
  assert.equal(await files.read("src/new.ts"), "new");
  await files.change("src/new.ts", "delete", "new", "");
  assert.equal(files.changed.has("src/new.ts"), true);
} finally { await rm(root, { recursive: true, force: true }); }
console.log("omp-inbox behavioral checks passed");
