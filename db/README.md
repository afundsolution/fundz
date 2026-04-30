# FUNDz Database

Use this folder for database structure, not production data.

Track these in Git:

- Schema notes.
- Migration files.
- Seed files with fake/sample data only.
- Restore runbooks.

Do not track these in Git:

- Real customer records.
- Production exports.
- Database dumps.
- Credentials or connection strings.

Production/user data should live in a managed database with automated backups and point-in-time recovery when available.
