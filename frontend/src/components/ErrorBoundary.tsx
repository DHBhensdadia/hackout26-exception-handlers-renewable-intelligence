import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Top-level error boundary so a render error in any route degrades to a
 * recoverable message instead of a blank page.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (import.meta.env.DEV) {
      console.error("[ErrorBoundary]", error, info.componentStack);
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback;

    return (
      <div className="crash" role="alert">
        <span className="crash__k">unexpected error</span>
        <h1 className="crash__title">Something went wrong.</h1>
        <p className="crash__body">
          The page hit an unrecoverable state. Reload to try again — if it persists, the run inputs may be the cause.
        </p>
        <div className="crash__actions">
          <button type="button" className="btn" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => window.location.reload()}>
            Reload page
          </button>
        </div>
        {import.meta.env.DEV && <pre className="crash__trace">{error.message}</pre>}
      </div>
    );
  }
}
