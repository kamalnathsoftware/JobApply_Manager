import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSend } from "../api/hooks";
import type { PersonalDetails } from "../api/types";
import { Button, Card, ErrorText, Field, PageHeader, inputCls } from "../components/ui";

const EMPTY: PersonalDetails = {
  date_of_birth: null, gender: "", marital_status: "", nationality: "", father_name: "", passport_number: "", disability_status: "",
  address: "", city: "", state: "", postal_code: "", country: "", alternate_phone: "", current_ctc: "", expected_ctc: "",
  notice_period: "", last_working_day: null, preferred_location: "", willing_to_relocate: "", work_authorization: "", requires_sponsorship: "",
};


const GENDER = ["Male", "Female", "Other", "Prefer not to say"];
const MARITAL = ["Single", "Married", "Divorced", "Widowed", "Prefer not to say"];
const DISABILITY = ["None", "Yes", "Prefer not to say"];
const NOTICE = ["Immediate joiner", "15 days", "30 days", "45 days", "60 days", "90 days", "More than 90 days"];
const WORK_AUTH = ["Yes – citizen", "Yes – permanent resident", "Yes – valid work permit / visa", "No – I need authorisation"];
const NATIONALITY = ["Indian", "American", "British", "Canadian", "Australian", "German", "French", "Singaporean", "Emirati", "Sri Lankan", "Nepalese", "Bangladeshi", "Other"];
const COUNTRY = ["India", "United States", "United Kingdom", "Canada", "Australia", "Germany", "France", "Singapore", "United Arab Emirates", "Sri Lanka", "Nepal", "Bangladesh", "Other"];
const STATE = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry", "Other"];

type TextKey = Exclude<keyof PersonalDetails, "date_of_birth" | "last_working_day" | "willing_to_relocate" | "requires_sponsorship">;

export default function Personal() {
  const { data } = useQuery({ queryKey: ["personal"], queryFn: () => api<PersonalDetails>("/personal-details") });
  const [f, setF] = useState<PersonalDetails>(EMPTY);
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (data) setF(data); }, [data]);
  const save = useSend<PersonalDetails, PersonalDetails>("PUT", "/personal-details", ["personal"]);
  const set = <K extends keyof PersonalDetails>(k: K, v: PersonalDetails[K]) => { setSaved(false); setF({ ...f, [k]: v }); };
  const text = (k: TextKey, label: string, ph?: string, hint?: string) => (
    <Field label={label} hint={hint}><input className={inputCls} value={f[k]} placeholder={ph} onChange={(e) => set(k, e.target.value)} /></Field>
  );
  // A dropdown that keeps a previously saved value even if it is not in the list (e.g. "chennai" typed earlier).
  const pick = (k: TextKey, label: string, options: string[], hint?: string) => {
    const cur = f[k];
    const opts = cur && !options.some((o) => o.toLowerCase() === cur.toLowerCase()) ? [cur, ...options] : options;
    const value = opts.find((o) => o.toLowerCase() === cur.toLowerCase()) ?? "";
    return (
      <Field label={label} hint={hint}>
        <select className={inputCls} value={value} onChange={(e) => set(k, e.target.value)}>
          <option value="">Not set – ask me</option>
          {opts.map((o) => <option key={o}>{o}</option>)}
        </select>
      </Field>
    );
  };
  const yesNo = (k: "willing_to_relocate" | "requires_sponsorship", label: string) => (
    <Field label={label}>
      <select className={inputCls} value={f[k]} onChange={(e) => set(k, e.target.value as "" | "Yes" | "No")}>
        <option value="">Not set – ask me</option><option>Yes</option><option>No</option>
      </select>
    </Field>
  );
  return (
    <div className="space-y-5">
      <PageHeader title="Personal details" subtitle="Used to fill application forms when they ask. Anything left empty is never guessed – the job waits for you in the Review Queue instead." />
      <p className="rounded bg-amber-50 p-3 text-sm text-amber-900">
        Stored encrypted on your own machine. Date of birth, passport number, father&apos;s name and disability status are <b>never sent to the AI provider</b>;
        they are only typed into forms by the worker when a question clearly asks for them. Fill in only what you are comfortable sharing with employers.
      </p>
      <Card>
        <h3 className="mb-3 font-semibold">About you</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Date of birth"><input type="date" className={inputCls} value={f.date_of_birth ?? ""} onChange={(e) => set("date_of_birth", e.target.value || null)} /></Field>
          {pick("gender", "Gender", GENDER)}
          {pick("marital_status", "Marital status", MARITAL)}
          {pick("nationality", "Nationality", NATIONALITY)}
          {text("father_name", "Father's name")}
          {text("passport_number", "Passport number")}
          {pick("disability_status", "Disability status", DISABILITY, "Only if forms ask for it")}
        </div>
      </Card>
      <Card>
        <h3 className="mb-3 font-semibold">Address & contact</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="md:col-span-2">{text("address", "Address", "Door no, street, area")}</div>
          {text("city", "City", "Chennai")}
          {pick("state", "State / province", STATE)}
          {text("postal_code", "PIN / postal code")}
          {pick("country", "Country", COUNTRY)}
          {text("alternate_phone", "Alternate phone", "+91…", "Your main phone and email come from the resume")}
        </div>
      </Card>
      <Card>
        <h3 className="mb-3 font-semibold">Job preferences</h3>
        <div className="grid gap-3 md:grid-cols-2">
          {text("current_ctc", "Current CTC", "6 LPA")}
          {text("expected_ctc", "Expected CTC", "9 LPA")}
          {pick("notice_period", "Notice period", NOTICE)}
          <Field label="Last working day" hint="The date you leave (or left) your current employer. Leave empty if not applicable.">
            <input type="date" className={inputCls} value={f.last_working_day ?? ""} onChange={(e) => set("last_working_day", e.target.value || null)} />
          </Field>
          {text("preferred_location", "Preferred work location", "Chennai, Bengaluru, Remote")}
          {yesNo("willing_to_relocate", "Willing to relocate?")}
          {pick("work_authorization", "Work authorisation", WORK_AUTH)}
          {yesNo("requires_sponsorship", "Needs visa sponsorship?")}
        </div>
      </Card>
      <ErrorText error={save.error} />
      <div className="flex items-center gap-3">
        <Button disabled={save.isPending} onClick={() => save.mutate(f, { onSuccess: () => setSaved(true) })}>{save.isPending ? "Saving…" : "Save details"}</Button>
        {saved && <span className="text-sm text-emerald-700">Saved ✓</span>}
      </div>
    </div>
  );
}
