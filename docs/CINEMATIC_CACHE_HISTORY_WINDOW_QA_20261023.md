# Master-cache history window audit

PR #23 master reuse scans only the newest 100 video_master rows; SQLite reproduction with 102 rows confirms older matching records are missed. This is not a full assembler test or media proof. A targeted project-and-source-digest query should preserve SHA-256 and probe checks. Review with PRs #8, #21, and #23 before integration. No owner media, deployment, or model inference was used.
