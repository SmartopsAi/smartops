function PageHeader({ eyebrow, title, description, meta }) {
  return (
    <div className="page-header">
      <div>
        {eyebrow ? <p className="page-header__eyebrow">{eyebrow}</p> : null}
        <h2>{title}</h2>
        {description ? <p className="page-header__description">{description}</p> : null}
      </div>
      {meta ? <div className="page-header__meta">{meta}</div> : null}
    </div>
  );
}

export default PageHeader;
