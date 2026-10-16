import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useSend } from "../api/hooks";
import type { PersonalDetails } from "../api/types";
import { Button, Card, ErrorText, Field, PageHeader, inputCls } from "../components/ui";

const EMPTY: PersonalDetails = {
  date_of_birth: null, gender: "", marital_status: "", nationality: "", father_name: "", passport_number: "", disability_status: "",
  address: "", city: "", state: "", postal_code: "", country: "", alternate_phone: "", current_ctc: "", expected_ctc: "",
  notice_period: "", preferred_location: "", willing_to_relocate: "", work_authorization: "", requires_sponsorship: "",
};

type TextKey = Exclude<keyof PersonalDetails, "date_of_birth" | "willing_to_relocate" | "requires_sponsorship">;

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
          {text("gender", "Gender", "Male / Female / Other")}
          {text("marital_status", "Marital status", "Single / Married")}
          {text("nationality", "Nationality", "Indian")}
          {text("father_name", "Father's name")}
          {text("passport_number", "Passport number")}
          {text("disability_status", "Disability status", "None", "Only if forms ask for it")}
        </div>
      </Card>
      <Card>
        <h3 className="mb-3 font-semibold">Address & contact</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <div className="md:col-span-2">{text("address", "Address", "Door no, street, area")}</div>
          {text("city", "City", "Chennai")}
          {text("state", "State / province", "Tamil Nadu")}
          {text("postal_code", "PIN / postal code")}
          {text("country", "Country", "India")}
          {text("alternate_phone", "Alternate phone", "+91…", "Your main phone and email come from the resume")}
        </div>
      </Card>
      <Card>
        <h3 className="mb-3 font-semibold">Job preferences</h3>
        <div className="grid gap-3 md:grid-cols-2">
          {text("current_ctc", "Current CTC", "6 LPA")}
          {text("expected_ctc", "Expected CTC", "9 LPA")}
          {text("notice_period", "Notice period", "30 days")}
          {text("preferred_location", "Preferred work location", "Chennai, Bengaluru, Remote")}
          {yesNo("willing_to_relocate", "Willing to relocate?")}
          {text("work_authorization", "Work authorisation", "Yes – Indian citizen")}
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
