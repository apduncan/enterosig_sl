"""
# Enterosignature Transformer
Transform GTDB taxonomic abundance tables to Enterosignature weights
"""
from importlib.resources import files
from typing import Collection, List, Tuple, Union
from datetime import date
import io
import zipfile as zf
import pandas as pd
import streamlit as st

import cvanmf.models
from cvanmf.denovo import Decomposition
from cvanmf.reapply import (EnteroException, ReapplyResult, transform_table)
import text

# Remove the big top margin to gain more space
# st.set_page_config(layout="wide")
hide_streamlit_style = """
<style>
    #root > div:nth-child(1) > div > div > div > div > section > div {padding-top: 0rem;}
    div[data-testid=column] {valign: middle}
</style>

"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# Constants for resource locations etc
ES_W_MATRIX: pd.DataFrame = cvanmf.models.five_es()
PLOTLY_WIDTH: int = 650


# STREAMLIT SPECIFIC FUNCTIONS
@st.cache_data
def _zip_items(items: Collection[Tuple[str, str]]
               ) -> io.BytesIO:
    """Create an in-memory zip file from a collection of objects, so it can be
    offered to a user for download.
    Using suggestions from https://stackoverflow.com/questions/2463770/
    # python-in-memory-zip-library."""
    zbuffer: io.BytesIO = io.BytesIO()
    with zf.ZipFile(zbuffer, "a", zf.ZIP_DEFLATED, False) as z:
        for name, contents in items:
            z.writestr(name, contents)
        # Always add the readme
        z.write(files("cvanmf.data").joinpath("README.txt"), arcname="README.txt")
    return zbuffer


# TODO(apduncan): Caching producing partly empty logs on reruns, might
# be confusing for users

class Logger:
    """Write log to screen as it occurs, but also collect so logs can be 
    written to a file in the results zip."""

    def __init__(self) -> None:
        self.__loglines: List[str] = []
        self.log(f"Date: {date.today()}", to_screen=False)

    def log(self, message: str, to_screen: bool = True) -> None:
        self.__loglines.append(message)
        if to_screen:
            st.write(message)

    def to_file(self) -> str:
        """Concatenate all messages to a single string for writing to 
        file."""
        return "\n".join(self.__loglines)


es_log: Logger = Logger()


# WRAPPER FUNCTIONS
# Wrap some long running functions, so we can apply the streamlit decorators
# without having to apply them to the commandline version of those same
# functions
@st.cache_resource
def _get_es_w() -> pd.DataFrame:
    return ES_W_MATRIX


def _transform_table(abd: pd.DataFrame,
                     family_rollup: bool = True) -> Decomposition:
    return transform_table(abundance=abd, rollup=family_rollup,
                           model_w=_get_es_w(),
                           hard_mapping={}, logger=es_log.log)


# APP CONTENT
# The app is quite long, so want to try and section it up so people don't 
# miss that they have to scroll for results etc
if "uploaded" not in st.session_state:
    st.session_state.uploaded = False

st.title(text.TITLE)

col_upload, col_opts = st.columns(spec=[0.8, 0.2])
abd_file = col_upload.file_uploader(
    label=text.UPLOAD_LABEL,
    help=text.UPLOAD_TOOLTIP
)
col_opts.markdown('<div style="height: 0.5ex">&nbsp</div>',
                  unsafe_allow_html=True)
opt_rollup: bool = col_opts.toggle(text.ROLLUP_LABEL, value=True,
                                   help=text.ROLLUP_TOOLTIP)
uploaded = abd_file is not None

expander_upload = st.expander(text.EXPANDER_UPLOAD, expanded=not uploaded)
expander_log = st.expander(text.EXPANDER_LOG, expanded=uploaded)
expander_results = st.expander(text.EXPANDER_RESULTS, expanded=uploaded)

with expander_upload:
    st.markdown(text.SUMMARY)
    st.markdown(text.INPUT_FORMAT)
    st.markdown(text.CAVEATS)

if abd_file is not None:
    try:
        # Attempt to transform the data and return Enterosignatures
        # Any step which fails due to some problem with the data should
        # raise an EnteroException
        # TODO(apduncan): Custom hashing to reduce time on large matrices?
        # TODO(apduncan): Allowing hard mapping to be provided
        # TODO(apduncan): Family rollup as a toggle
        abd_tbl = pd.read_csv(abd_file, sep="\t", index_col=0)
        with expander_log:
            transformed: Decomposition = _transform_table(
                abd=abd_tbl, family_rollup=opt_rollup)
            # Apply color mappings
            transformed.colors = dict(
                ES_Esch="#483838",
                ES_Bifi="#009E73",
                ES_Bact="#E69F00",
                ES_Prev="#D55E00",
                ES_Firm="#023e8a"
            )

        # Zip up new W, new abundance, new H (enterosig weights), and model fit
        # Can't use the Decomposition.save method as don't want to write to disk
        # in a potentially multi-user environment we don't control.
        # TODO: Make streamlit output format match the .save() format
        res_zip: io.BytesIO = _zip_items([
            ("w.tsv", transformed.w.to_csv(sep="\t")),
            ("h.tsv", transformed.h.to_csv(sep="\t")),
            ("w_scaled.tsv", transformed.scaled('w').to_csv(sep="\t")),
            ("h_scaled.tsv", transformed.scaled('h').to_csv(sep="\t")),
            ("x.tsv", transformed.parameters.x.to_csv(sep="\t")),
            ("model_fit.tsv", transformed.model_fit.to_csv(sep="\t")),
            ("quality_measures.tsv", transformed.quality_series.to_csv(sep="\t")),
            ("primary_signatures.tsv", transformed.primary_signature.to_csv(sep="\t")),
            ("representative_signatures.tsv",
             transformed.representative_signatures().to_csv(sep="\t")),
            ("monodominant_samples.tsv",
             transformed.monodominant_samples().to_csv(sep="\t")),
            ("taxon_mapping.tsv",
             transformed.feature_mapping.to_df().to_csv(sep="\t")),
            ("log.txt", es_log.to_file())
        ])

        with expander_results:
            st.download_button(
                label=text.DOWNLOAD_LABEL,
                data=res_zip,
                file_name="apply_es_results.zip"
            )

            st.markdown(text.RESULTS)

            st.markdown(text.WEIGHT_PLOT_TITLE)
            st.markdown(text.WEIGHT_PLOT_CAPTION)
            # Provide a simple visualisations of the ES
            st.write(
                transformed.plot_relative_weight().savefig()
            )

            # Provide a simple visualisation of the model fit
            # TODO(apduncan): Bin count customisation, spline, explain fit
            st.markdown(text.MODELFIT_PLOT_TITLE)
            st.write(
                transformed.plot_modelfit().draw()
            )

            # Only perform PCoA if there are a smallish (<100) number of samples
            st.markdown(text.PCOA_PLOT_TITLE)
            if transformed.h.shape[1] < 500:
                st.write(
                    transformed.plot_pcoa().draw()
                )

            st.session_state.uploaded = True

    except EnteroException as err:
        st.write(f"Unable to transform: {err}")
