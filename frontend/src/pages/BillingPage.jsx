import { useState, useEffect } from "react";
import { useAuth } from "../auth";
import BACKEND from "../api/client";
import { useToast } from "../components/Toast";

const PLAN_COLORS = { starter: "#6B7280", professional: "#3B82F6", enterprise: "#8B5CF6" };

export default function BillingPage() {
  const { getAuthHeaders, user } = useAuth();
  const toast = useToast();
  const [plans, setPlans] = useState([]);
  const [subscription, setSubscription] = useState(null);
  const [activePlan, setActivePlan] = useState("starter");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [pRes, sRes] = await Promise.all([
          fetch(`${BACKEND}/api/v3/billing/plans`, { headers: getAuthHeaders() }),
          fetch(`${BACKEND}/api/v3/billing/subscription`, { headers: getAuthHeaders() }),
        ]);
        const pData = await pRes.json();
        const sData = await sRes.json();
        setPlans(pData.plans || []);
        setSubscription(sData);
        if (sData?.plan) setActivePlan(sData.plan.plan_id);
      } catch (e) {
        toast.error("Failed to load billing info");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function handleSelectPlan(plan) {
    if (plan.price === 0) {
      toast.success("Free plan activated");
      setActivePlan("starter");
      return;
    }
    try {
      const res = await fetch(`${BACKEND}/api/v3/billing/create-order`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ plan_id: plan.plan_id }),
      });
      const data = await res.json();
      if (data.free) {
        toast.success("Plan activated!");
        setActivePlan(plan.plan_id);
        return;
      }
      if (!data.order) {
        toast.error("Failed to create order");
        return;
      }
      const options = {
        key: data.key_id,
        amount: data.order.amount,
        currency: "INR",
        name: "InvoSync",
        description: `${plan.name} Plan - ₹${plan.price}/month`,
        order_id: data.order.id,
        prefill: { email: user?.email || "" },
        handler: async function (response) {
          const vRes = await fetch(`${BACKEND}/api/v3/billing/verify-payment`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...getAuthHeaders() },
            body: JSON.stringify({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
              plan_id: plan.plan_id,
            }),
          });
          if (vRes.ok) {
            toast.success(`${plan.name} plan activated!`);
            setActivePlan(plan.plan_id);
          } else {
            toast.error("Payment verification failed");
          }
        },
        modal: { ondismiss: () => toast.error("Payment cancelled") },
      };
      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch (e) {
      toast.error("Payment error: " + e.message);
    }
  }

  if (loading) {
    return <div className="text-center text-gray-400 py-12 animate-pulse">Loading plans...</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">Billing & Plans</h1>
        <p className="text-gray-400 text-sm">Choose a plan that fits your practice</p>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {plans.map((plan) => {
          const isActive = activePlan === plan.plan_id;
          return (
            <div
              key={plan.plan_id}
              className={`premium-card-flat p-6 flex flex-col ${isActive ? "ring-2 ring-blue-500/50" : ""}`}
            >
              <div className="flex items-center gap-2 mb-1">
                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: PLAN_COLORS[plan.plan_id] || "#6B7280" }} />
                <h2 className="text-lg font-semibold text-white">{plan.name}</h2>
              </div>
              <div className="mt-2 mb-4">
                <span className="text-3xl font-bold text-white">₹{plan.price}</span>
                <span className="text-gray-400 text-sm ml-1">/month</span>
              </div>
              {plan.price === 0 && <div className="text-green-400 text-xs mb-3">Free forever — no card needed</div>}

              <div className="flex-1 space-y-2 mb-6">
                {plan.features.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm text-gray-300">
                    <svg className="w-4 h-4 text-green-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    {f}
                  </div>
                ))}
              </div>

              <button
                onClick={() => handleSelectPlan(plan)}
                disabled={isActive}
                className={`w-full py-2.5 rounded-lg text-sm font-medium transition-all ${
                  isActive
                    ? "bg-gray-700 text-gray-400 cursor-not-allowed"
                    : plan.price === 0
                    ? "bg-gray-600 text-white hover:bg-gray-500"
                    : "premium-btn-primary"
                }`}
              >
                {isActive ? "Current Plan" : plan.price === 0 ? "Get Started Free" : "Subscribe"}
              </button>
            </div>
          );
        })}
      </div>

      {subscription?.subscription && (
        <div className="premium-card-flat p-4">
          <h3 className="text-sm font-medium text-gray-300 mb-2">Subscription Details</h3>
          <div className="text-sm text-gray-400 space-y-1">
            <div>Status: <span className={`font-medium ${subscription.active ? "text-green-400" : "text-yellow-400"}`}>{subscription.active ? "Active" : "Inactive"}</span></div>
            {subscription.subscription.razorpay_subscription_id && (
              <div>Razorpay ID: {subscription.subscription.razorpay_subscription_id}</div>
            )}
            <div>Last updated: {subscription.subscription.updated_at || "N/A"}</div>
          </div>
        </div>
      )}

      <div className="premium-card-flat p-4 text-sm text-gray-400">
        Need help? Contact us at support@invosync.app or use the settings page to reach out.
      </div>
    </div>
  );
}
