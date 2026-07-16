const BACKEND = import.meta.env.VITE_API_URL || (
  window.location.hostname === "localhost" ? "" : "https://invosync-backend-yjfa.onrender.com"
);

export default BACKEND;

export function safeJson(r) {
  if (!r.ok) return Promise.reject(new Error(r.status + " " + r.statusText));
  return r.json().catch(() => ({}));
}

export const STATE_CODES = [
  "01-Jammu & Kashmir","02-Himachal Pradesh","03-Punjab","04-Chandigarh","05-Uttarakhand","06-Haryana","07-Delhi","08-Rajasthan","09-Uttar Pradesh","10-Bihar","11-Sikkim","12-Arunachal Pradesh","13-Nagaland","14-Manipur","15-Mizoram","16-Tripura","17-Meghalaya","18-Assam","19-West Bengal","20-Jharkhand","21-Odisha","22-Chhattisgarh","23-Madhya Pradesh","24-Gujarat","25-Daman & Diu","26-Dadra & Nagar Haveli","27-Maharashtra","28-Andhra Pradesh (old)","29-Karnataka","30-Goa","31-Lakshadweep","32-Kerala","33-Tamil Nadu","34-Puducherry","35-Andaman & Nicobar","36-Telangana","37-Andhra Pradesh (new)"
];
