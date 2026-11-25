# Book context and resumable full-book authoring

Approved scope: independent per-book work context; canonical content and progress on disk; resumable bounded source reads; no reduction of full-book completeness; sync generic skill changes to GitHub.

- Add a local book context sidecar bound to one pipeline config and source fingerprint. Generate a concise handoff for a fresh conversation, without creating chats or claiming to reset a host model's context.
- Bounded read receipts retain exact source offsets. Issuing a packet never marks it read. Explicit acknowledgment advances the cursor atomically; interrupt/retry remains idempotent.
- Keep chapter checkpoints bound to actual canonical record hashes, separate source/content review passes and global completeness notes. Track extracted visual assets separately. Changed inputs make reviews stale.
- Full-book public preparation/deployment for attached contexts requires all source ranges, chapters, visual dispositions and explicit global review. These records attest execution; they do not prove semantic completeness by themselves.
- Existing configs remain compatible and never gain completion status through migration. New author-led books initialize/attach the context before extension. Existing system-learning review contracts remain authoritative.
- Test interruptions, replay, changed sources/records/outline/visuals, incomplete publication and clean completion with synthetic fixtures; check an existing unfinished book read-only. Install only changed skill files with backup and synchronize reviewed generic changes, excluding all private book data.
