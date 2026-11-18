export default function PageHeading({ title, subtitle, eyebrow, actions }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow ? (
          <p className="mb-1.5 text-[10.5px] font-bold uppercase tracking-[0.16em] text-primary">{eyebrow}</p>
        ) : null}
        <h1 className="text-[28px] font-extrabold leading-tight tracking-tight text-ink sm:text-[30px]">{title}</h1>
        {subtitle ? <p className="mt-1.5 text-[12.5px] font-medium text-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
