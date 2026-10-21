"""Path checks that prevent a client build from overwriting its source executable."""
import os
from pathlib import Path


def ensure_distinct_output(source, output):
    source = Path(source)
    output = Path(output)

    source_resolved = source.resolve(strict=False)
    output_resolved = output.resolve(strict=False)
    if source_resolved == output_resolved:
        raise ValueError(f"build output aliases source executable: {output}")

    try:
        aliases_source = os.path.samefile(source, output)
    except FileNotFoundError:
        pass
    else:
        if aliases_source:
            raise ValueError(f"build output is the same file as source executable: {output}")

    return output
