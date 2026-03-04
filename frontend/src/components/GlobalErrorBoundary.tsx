import { Component, ErrorInfo, ReactNode } from "react";

interface Props {
    children?: ReactNode;
}

interface State {
    hasError: boolean;
}

/**
 * Catches rendering errors in child components, particularly useful for
 * handling React.lazy chunk load failures after a new deployment.
 */
export class GlobalErrorBoundary extends Component<Props, State> {
    public state: State = {
        hasError: false,
    };

    public static getDerivedStateFromError(error: Error): State {
        void error;
        return { hasError: true };
    }

    public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
        console.error("Uncaught error:", error, errorInfo);
    }

    private handleReload = () => {
        window.location.reload();
    };

    public render() {
        if (this.state.hasError) {
            return (
                <div className="flex h-screen w-full items-center justify-center bg-gray-50 px-4">
                    <div className="max-w-md text-center">
                        <h2 className="mb-3 text-2xl font-bold text-gray-800">
                            Oops! Something went wrong
                        </h2>
                        <p className="mb-6 text-gray-600">
                            The application encountered an unexpected error. This might be due to a network fluctuation or a recent system update. Please reload the page to continue.
                        </p>
                        <button
                            type="button"
                            onClick={this.handleReload}
                            className="rounded-md bg-brand px-6 py-2.5 font-medium text-white shadow-sm transition-colors hover:bg-brand/90 focus:outline-none focus:ring-2 focus:ring-brand focus:ring-offset-2"
                        >
                            Reload Page
                        </button>
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}
