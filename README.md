# Classroom NG

A single-school web app for Nigerian secondary classes JSS1 to SS3. It runs on Python 3.10 or later and stores school records in SQLite.

## Start the server

From this directory, set an initial administrator password and start the server.

```bash
read -rsp 'Initial administrator password (12 or more characters): ' SCHOOL_PASSWORD
echo
export SCHOOL_PASSWORD
python3 app.py
```

Open http://127.0.0.1:8000 and sign in as **admin**. The initial password is only used when creating the database. An administrator can issue teacher and student accounts from **School accounts**. Teachers can issue student accounts. Students receive access to the class assigned by staff and can change their own password.

## Run an assessment

1. Save a lesson note with its topic, subject, class and term. Select Publish to make it available to students in that class.
2. Select the source note in **Exams** and draft objective and theory questions. Drafts use sentence and word templates from the note. Review the questions, options, marks and guides before publishing. You can also write questions manually.
3. Print the paper and marking guide separately or let students open the published exam from their accounts. Each student can submit once.
4. Mark theory answers under **Submissions**. Objective questions are marked on submission. Saving and releasing marks makes the result available in the student's account.

## Storage and deployment

The application ships as a local pilot. It listens on the local computer by default, and opening that address on another device will not reach the school server. For remote student access, deploy it behind an HTTPS reverse proxy with a production process manager, sign-in rate limiting, and persistent storage. Set SCHOOL_SECURE_COOKIE=1 behind HTTPS. SCHOOL_HOST, PORT and SCHOOL_DB configure the bind address, port and database file. Back up the database and restrict access to its files. The included Python HTTP server is intended for the pilot.

Run python3 check.py to verify the core server workflow with temporary test data.

## Sites hosting

Run `node build.mjs` to package the hosted Worker. The hosted version uses the `DB` D1 binding and the SQL migration in `drizzle/`. Set the `SCHOOL_PASSWORD` runtime secret before first administrator sign-in. Use the portal's Change password screen to replace the bootstrap password after the first sign-in.
