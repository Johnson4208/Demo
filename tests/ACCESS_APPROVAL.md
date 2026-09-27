# Administrator access approval

SolvAI37 changes self-registration into an approval workflow. A submitted
request does not create an active account and does not sign the requester in.

Set `SOLVAI_ALLOW_REGISTRATION=1` to display the request form. Set it to `0`
for administrator-created accounts only.

## Administrator workflow

1. Sign in using the administrator account configured with
   `SOLVAI_ADMIN_EMAIL` and `SOLVAI_ADMIN_PASSWORD`.
2. Open the account menu and select **Access center**, or visit
   `/admin/users`.
3. Review **Pending access requests**. Confirm the name, email, stated reason,
   request time, device label, and privacy-safe network identifier.
4. Select the minimum required role:
   - **Viewer** can use research and analytics.
   - **Editor** can also upload financial statements and run indexing.
5. Optionally enter a private audit note, then select **Approve access** or
   **Reject**.

Approval activates the account immediately. The requester signs in with the
password they chose when submitting the request. The administrator never sees
that password or its hash.

## Database behavior

- Pending requests live in the `access_requests` table inside the existing
  persistent `financial_ai.sqlite3` database.
- Only one pending request may exist for an email address.
- Approval is transactional: the account and review record are saved together.
- Rejection erases the temporary credential hash.
- Approval/rejection actions are written to `admin_audit`.
- Reviewed requests follow the existing security-history retention policy;
  pending requests are not automatically removed.

Keep the existing Docker volume during upgrades so pending requests and user
accounts survive container rebuilds.
