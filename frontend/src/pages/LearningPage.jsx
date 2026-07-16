import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import CorrectionMemoryUI from "../components/CorrectionMemoryUI";

export default function LearningPage() {
  const { getAuthHeaders } = useAuth();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${BACKEND}/api/v3/learning/stats`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function statCard(label, value, color) {
    return (
      <div className="premium-card-flat p-4 text-center">
        <div className={`text-2xl font-bold ${color}`}>{value ?? "—"}</div>
        <div className="text-xs text-gray-500 mt-1">{label}</div>
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fadeInUp">
      <div className="premium-card p-5">
        <h2 className="text-sm font-semibold text-gray-200 mb-4">Learning Dashboard</h2>

        {loading ? (
          <div className="flex justify-center py-8">
            <div className="w-6 h-6 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              {statCard("Corrections", stats?.corrections_count, "text-indigo-400")}
              {statCard("Accuracy", stats?.correction_accuracy != null ? `${stats.correction_accuracy}%` : "—", "text-green-400")}
              {statCard("Exact Matches", stats?.exact_matches, "text-blue-400")}
              {statCard("Fuzzy Matches", stats?.fuzzy_matches, "text-yellow-400")}
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              {statCard("NLP Fallbacks", stats?.nlp_fallbacks, "text-purple-400")}
              {statCard("Suspense Fallbacks", stats?.suspense_fallbacks, "text-red-400")}
              {statCard("Total Resolved", stats?.total_resolutions, "text-gray-300")}
            </div>

            <div className="border-t border-white/5 pt-4">
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Correction Memory</h3>
              <CorrectionMemoryUI />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
