import { Link } from "react-router-dom";

/** Any address the app does not know, for example a mistyped link. */
export function NotFoundPage() {
  return (
    <main className="login">
      <h1>Page not found</h1>
      <p>There is no page at this address.</p>
      <Link to="/">Go to the overview</Link>
    </main>
  );
}
