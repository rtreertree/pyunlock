"""Build small representative PDFs without personal data or binary fixtures."""

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


def make_pdf(path: Path, *, rich: bool = False) -> Path:
    """Create two pages, optionally with document and page-level structures."""
    writer = PdfWriter()
    first = writer.add_blank_page(width=300, height=300)
    second = writer.add_blank_page(width=300, height=300)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    image = DecodedStreamObject()
    image.set_data(bytes([20, 100, 220]))
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    if rich:
        resources[NameObject("/XObject")] = DictionaryObject(
            {NameObject("/Im0"): writer._add_object(image)}
        )
    first[NameObject("/Resources")] = resources
    content = DecodedStreamObject()
    drawing = b"BT /F1 14 Tf 30 250 Td (Synthetic test document) Tj ET\n"
    if rich:
        drawing += b"q 20 0 0 20 30 200 cm /Im0 Do Q\n"
    content.set_data(drawing)
    first[NameObject("/Contents")] = writer._add_object(content)
    writer.add_metadata(
        {"/Title": "Synthetic PDF – ทดสอบ", "/Author": "pyunlock tests"}
    )
    if rich:
        writer.add_outline_item("Chapter One", 0)
        writer.add_attachment("notes.txt", b"Synthetic attachment\n")
        link = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): ArrayObject(
                    [NumberObject(value) for value in (20, 20, 100, 45)]
                ),
                NameObject("/Dest"): ArrayObject(
                    [second.indirect_reference, NameObject("/Fit")]
                ),
            }
        )
        note = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Text"),
                NameObject("/Rect"): ArrayObject(
                    [NumberObject(value) for value in (110, 20, 130, 45)]
                ),
                NameObject("/Contents"): TextStringObject("Synthetic annotation"),
            }
        )
        first[NameObject("/Annots")] = ArrayObject(
            [writer._add_object(link), writer._add_object(note)]
        )
        field = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/T"): TextStringObject("customer"),
                NameObject("/V"): TextStringObject("Ada Example"),
                NameObject("/Rect"): ArrayObject(
                    [FloatObject(value) for value in (30, 200, 200, 220)]
                ),
                NameObject("/DA"): TextStringObject("/F1 12 Tf 0 g"),
                NameObject("/P"): second.indirect_reference,
            }
        )
        field_reference = writer._add_object(field)
        second[NameObject("/Annots")] = ArrayObject([field_reference])
        writer._root_object[NameObject("/AcroForm")] = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Fields"): ArrayObject([field_reference]),
                    NameObject("/NeedAppearances"): BooleanObject(True),
                    NameObject("/DR"): DictionaryObject(
                        {
                            NameObject("/Font"): DictionaryObject(
                                {NameObject("/F1"): font}
                            )
                        }
                    ),
                }
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer.write(stream)
    return path


def encrypt_pdf(
    source: Path,
    destination: Path,
    *,
    password: str = "test-password",
    owner_password: str | None = None,
    algorithm: str = "AES-256",
) -> Path:
    with source.open("rb") as stream:
        writer = PdfWriter(clone_from=PdfReader(stream))
        writer.encrypt(
            user_password=password,
            owner_password=password if owner_password is None else owner_password,
            algorithm=algorithm,
        )
        with destination.open("wb") as output:
            writer.write(output)
    return destination


def content_snapshot(path: Path, password: str | None = None) -> dict:
    """Compare supported content independently from PDF byte serialization."""
    with path.open("rb") as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted:
            assert password is not None
            assert reader.decrypt(password)
        annotations = []
        links = []
        images = []
        for index, page in enumerate(reader.pages):
            for reference in page.get("/Annots", []):
                annotation = reference.get_object()
                annotations.append(
                    (
                        index,
                        str(annotation.get("/Subtype")),
                        str(annotation.get("/Contents", "")),
                        tuple(annotation.get("/Rect", [])),
                    )
                )
                if annotation.get("/Subtype") == "/Link":
                    target = annotation["/Dest"][0].get_object()
                    target_index = next(
                        number
                        for number, candidate in enumerate(reader.pages)
                        if candidate.indirect_reference == target.indirect_reference
                    )
                    links.append((index, target_index))
            image_resources = page.get("/Resources", {}).get("/XObject", {})
            for name, reference in image_resources.items():
                resource = reference.get_object()
                if resource.get("/Subtype") == "/Image":
                    images.append(
                        (
                            index,
                            str(name),
                            resource["/Width"],
                            resource["/Height"],
                            resource.get_data(),
                        )
                    )
        return {
            "page_count": len(reader.pages),
            "text": [page.extract_text() for page in reader.pages],
            "metadata": dict(reader.metadata),
            "outlines": [item.title for item in reader.outline],
            "annotations": annotations,
            "links": links,
            "images": images,
            "attachments": {
                name: list(contents) for name, contents in reader.attachments.items()
            },
            "forms": {
                name: field.get("/V")
                for name, field in (reader.get_fields() or {}).items()
            },
        }
