import { Link } from "react-router-dom";
import { Button } from "@/components/ui";

export default function NotFound() {
  return (
    <main className="notfound">
      <span className="eyebrow">Error 404</span>
      <h1 className="display">This page has no forecast.</h1>
      <p className="lead">
        The route you requested does not exist. Head back to the landing page or open the decision console.
      </p>
      <div className="notfound__actions">
        <Button to="/">Back to home</Button>
        <Button to="/dashboard" variant="ghost">
          Open dashboard
        </Button>
      </div>
      <span className="footmark">
        <Link to="/">re-forecast</Link>
      </span>
    </main>
  );
}
