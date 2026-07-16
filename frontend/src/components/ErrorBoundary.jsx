import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center p-8">
          <div className="premium-card-flat p-8 max-w-lg text-center space-y-4">
            <p className="text-red-400 text-lg font-semibold">Something went wrong</p>
            <p className="text-gray-400 text-sm">{this.state.error.message}</p>
            <button onClick={() => this.setState({ error: null })} className="premium-btn-primary px-6 py-2">Try Again</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
