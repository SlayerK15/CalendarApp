# Public Google sign-in

The app is still an OAuth **Testing** application. The repository and Render API key cannot change Google Cloud project settings or grant Google verification. A Google Cloud project owner must perform the console steps below, and Google makes the approval decision.

## Prepared application URLs

- Home: https://calendarapp-2r1h.onrender.com/
- Privacy: https://calendarapp-2r1h.onrender.com/privacy
- Terms: https://calendarapp-2r1h.onrender.com/terms
- Callback: https://livetimetable-api.onrender.com/api/auth/google/callback
- OAuth client ID: `620420591574-1r1maa5bj1jsv6grpv0am7lkpcnmar51.apps.googleusercontent.com`

The privacy and terms pages describe the implemented app. The operator must review them and supply their public support email in Google Auth Platform. For verification, configure a domain whose ownership the operator can verify; an `onrender.com` subdomain is a deployment address, not evidence that the operator owns `onrender.com`.

## Current permissions and purpose

| Permission | App use |
| --- | --- |
| openid, email, profile | Identify the signed-in account |
| spreadsheets.readonly | Read native Google Sheets timetables |
| drive.readonly | Download the configured Excel timetable and register change watches |
| calendar.app.created | Create and reconcile the app's College Timetable calendar |
| calendar.calendarlist.readonly | Recover an app-created calendar after interrupted creation |

**Drive read-only is a restricted scope**, despite allowing no writes. The server processes that data, so Google's restricted-scope verification and security assessment requirements must be reviewed. Do not describe the app as verified, or promise unrestricted public access, until Google approves the actual scope set.

## Console work

1. Open the AItools project in Google Auth Platform. Verify that the client ID matches the production request.
2. In Branding, use LiveTimetable as the name, configure a monitored support email and developer contact, and add the home/privacy/terms URLs. Verify ownership of the domain used for verification.
3. In Data Access, declare the exact scopes above and explain each purpose. Prepare a demonstration of login, each consent permission, timetable selection, calendar creation, update/cancellation handling, revocation and deletion requests. Use a test account and a timetable the operator may share with reviewers.
4. In Audience, change the external app from Testing to Production when the public launch is ready. Publishing removes the test-user-only audience restriction, but **does not itself complete verification** or remove Google's unverified-app restrictions.
5. Submit the required branding/scope verification through Verification Center, respond to Google's requests, and complete any required security assessment.
6. Confirm approval, then test with a Google account not on the test-user list.

No project publishing or verification submission has been performed by this code change.

## Lower-permission architecture to consider before a large launch

For one college-owned timetable, ask its owner to grant a dedicated server identity access to that file. Read and parse the source once on the server and fan out the normalized timetable to authorized student subscriptions. Student OAuth would then need account/calendar access rather than broad access to every student's Drive. Define which students may access the timetable and obtain source-owner approval before sharing a cached timetable across accounts. Calendar and branding verification requirements still apply as determined by Google.

For user-selected private files, Google's recommended `drive.file` plus Picker model is another option. It requires a different consent/selection flow; simply replacing `drive.readonly` with `drive.file` will break access to the existing configured file. The current server-only Google-token design must also be considered before introducing Picker.

Sources checked 11 September 2026: [Drive scope classifications](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), [restricted-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification), [Calendar scopes](https://developers.google.com/workspace/calendar/api/auth).
