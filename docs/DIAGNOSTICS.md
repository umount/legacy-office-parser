# Diagnostic codes

Codes are assigned at emission sites. Message wording may change; code meanings
are stable identifiers whose meanings are not reassigned. Additions and any
deprecations follow the documented release compatibility policy. Unknown future codes must be retained.
Diagnostics are deduplicated by code and message, not occurrence counts, severity,
source locations or an exhaustive inventory of omissions. Existing `warnings`
remain strings. `Document.diagnostics` returns `Diagnostic(code, message)` objects;
`to_dict()` adds `diagnostics: [{"code": ..., "message": ...}]` when warnings exist.
An empty list is omitted. Caller-added plain strings use `unclassified_warning`.
Warning messages are not source locations or severity classifications. No code is inferred by matching runtime message text.

- `doc_a_doc_story_has_no_final_paragraph_mark_trailing`: A DOC story has no final paragraph mark; trailing text is retained.
- `doc_cell_mark_without_table_membership_was_retained_as_a`: Cell mark without table membership was retained as a paragraph boundary.
- `doc_comment_authors_are_absent_initials_are_retained_without`: DOC comment authors are absent; initials are retained without inferring names.
- `doc_comment_final_paragraph_has_unknown_table_membership_its`: DOC comment final paragraph has unknown table membership; its body is omitted.
- `doc_comment_ink_is_not_rendered_proven_textual_bodies`: DOC comment ink is not rendered; proven textual bodies retain stored order.
- `doc_comment_marker_cfspec_is_unknown_its_unproven_body`: DOC comment marker CFSpec is unknown; its unproven body is omitted.
- `doc_comment_ownership_plc_is_absent_unproven_comment_story`: DOC comment ownership PLC is absent; unproven comment story text is omitted.
- `doc_comment_reply_ancestry_is_unavailable_relationship_metadata_is`: DOC comment reply ancestry is unavailable; relationship metadata is omitted without dropping the body.
- `doc_comment_selection_bookmark_is_unresolved_reference_ownership_is`: DOC comment selection bookmark is unresolved; reference ownership is retained.
- `doc_comment_selection_validity_is_unproven_source_selection_bounds`: DOC comment selection validity is unproven; source selection bounds are omitted.
- `doc_comment_story_has_an_unassigned_prefix_only_plc`: DOC comment story has an unassigned prefix; only PLC-owned bodies are considered.
- `doc_conditional_table_visibility_has_no_proven_stable_rectangular_context`: Conditional table visibility has no proven stable rectangular context; unconditional visibility is retained.
- `doc_covered_merged_cells_contain_text_their_text_is_retained`: Covered merged cells contain text; their text is retained at its original coordinate.
- `doc_embedded_objects_and_drawings_are_omitted_textbox_stories_are`: Embedded objects and drawings are omitted; textbox stories are extracted separately.
- `doc_external_table_properties_supplied_no_supported_cell_geometry_inline`: External table properties supplied no supported cell geometry; inline fallback properties are used.
- `doc_far_east_doc_flag_is_set_language_specific_legacy`: Far East DOC flag is set; language-specific legacy encoding is not interpreted.
- `doc_fields_use_stored_results_field_instructions_are_not_evaluated`: Fields use stored results; field instructions are not evaluated.
- `doc_font_dependent_symbol_codes_are_retained_verbatim_no_font`: Font-dependent symbol codes are retained verbatim; no font-specific Unicode glyph mapping is applied.
- `doc_header_settings_unresolved`: Malformed optional header settings; affected selection metadata is unknown and source text is retained.
- `doc_header_variants_and_textbox_placement_are_not_modeled`: Header variants and textbox placement are not modeled.
- `doc_hidden_or_deleted_paragraph_cell_marks_retain_their_structural`: Hidden or deleted paragraph/cell marks retain their structural boundaries; revision merging is not modeled.
- `doc_incomplete_or_zero_width_table_grids_cannot_be_normalized`: Incomplete or zero-width table grids cannot be normalized; physical cell coordinates are retained.
- `doc_incomplete_table_row_has_no_proven_table_style_context`: Incomplete table row has no proven table-style context; available text is retained.
- `doc_invalid_horizontal_merge_range_was_ignored`: Invalid horizontal merge range was ignored.
- `doc_invalid_symbol_unicode_surrogate_was_replaced_with_u_fffd`: Invalid symbol Unicode surrogate was replaced with U+FFFD.
- `doc_invalid_utf_16_was_replaced_with_u_fffd`: Invalid UTF-16 was replaced with U+FFFD.
- `doc_legacy_external_papx_properties_are_unsupported_available_inline_properties`: Legacy external PAPX properties are unsupported; available inline properties are used.
- `doc_legacy_table_geometry_is_unsupported_explicit_cell_marks_are`: Legacy table geometry is unsupported; explicit cell marks are retained.
- `doc_note_comment_output_anchors_are_unresolved_source_cps_are`: Note/comment output anchors are unresolved; source CPs are not output offsets.
- `doc_note_comment_reference_marks_are_omitted_note_stories_are`: Note/comment reference marks are omitted; note stories are extracted separately.
- `doc_note_reference_cfspec_is_not_established_its_output_anchor`: Note reference CFSpec is not established; its output anchor is unresolved.
- `doc_note_reference_plc_is_absent_or_its_count_differs`: Note reference PLC is absent or its count differs from the bodies; note bodies are unlinked.
- `doc_note_references_have_no_corresponding_bodies_no_note_relationships`: Note references have no corresponding bodies; no note relationships are emitted.
- `doc_note_text_plc_is_absent_the_whole_story_is`: Note text PLC is absent; the whole story is retained without note relationships.
- `doc_note_text_plc_leaves_an_unassigned_prefix_the_whole`: Note text PLC leaves an unassigned prefix; the whole story is retained without note relationships.
- `doc_orphan_horizontal_merge_continuation_was_retained_as_a_normal`: Orphan horizontal merge continuation was retained as a normal cell.
- `doc_outer_table_markers_at_nested_depth_were_retained_as`: Outer table markers at nested depth were retained as paragraph boundaries.
- `doc_paragraph_formatting_is_absent_table_structure_cannot_be_established`: Paragraph formatting is absent; table structure cannot be established.
- `doc_piece_table_contains_cps_outside_the_declared_stories_these`: Piece table contains CPs outside the declared stories; these are excluded.
- `doc_preferred_table_widths_and_automatic_table_layout_are_not`: Preferred table widths and automatic table layout are not evaluated; explicit cell geometry is used.
- `doc_row_terminator_contains_content_content_is_retained_as_a`: Row terminator contains content; content is retained as a cell.
- `doc_some_characters_have_no_chpx_coverage_symbol_and_visibility`: Some characters have no CHPX coverage; symbol and visibility properties may be missing.
- `doc_some_note_comment_references_could_not_be_linked_to`: Some note/comment references could not be linked to an output paragraph or cell.
- `doc_some_paragraphs_have_no_papx_coverage_their_table_membership`: Some paragraphs have no PAPX coverage; their table membership is unknown.
- `doc_style_relative_cfspec_is_not_resolved_without_a_stylesheet`: Style-relative CFSpec is not resolved without a stylesheet; available symbol codes are retained.
- `doc_symbol_control_code_is_retained_literally_not_interpreted_as`: Symbol control code is retained literally, not interpreted as a DOC delimiter.
- `doc_symbol_font_table_is_absent_symbol_codes_are_retained`: Symbol font table is absent; symbol codes are retained without font interpretation.
- `doc_table_definition_and_cell_marks_disagree_observed_cells_are`: Table definition and cell marks disagree; observed cells are retained without inferred cells.
- `doc_table_ends_without_a_row_terminator_the_incomplete_row`: Table ends without a row terminator; the incomplete row is retained.
- `doc_table_styles_hidden_text_is_evaluated_only_for_supported`: Table styles: hidden text is evaluated only for supported contexts; other table-style formatting is not modeled.
- `doc_textbox_plc_is_absent_active_ranges_cannot_be_verified`: Textbox PLC is absent; active ranges cannot be verified. The full textbox story is retained and may include reserved text.
- `doc_this_compact_piece_formatting_prm0_property_is_not_evaluated`: This compact piece formatting (Prm0) property is not evaluated.
- `doc_unbalanced_doc_field_delimiters_were_encountered`: Unbalanced DOC field delimiters were encountered.
- `doc_unsupported_control_characters_were_omitted_from_extracted_text`: Unsupported control characters were omitted from extracted text.
- `doc_vertical_merge_without_a_defined_cell_was_ignored`: Vertical merge without a defined cell was ignored.
- `doc_vertical_merge_without_a_matching_explicit_grid_was_not`: Vertical merge without a matching explicit grid was not applied.
- `heading_name_fallback`: RTF heading levels inferred from built-in style names.
- `hidden_text_omitted`: Hidden or deleted text omitted.
- `invalid_encoded_text_replaced`: Invalid encoded text replaced.
- `odf_automatic_pagination_is_not_computed_next_master_pages`: ODF automatic pagination is not computed; next master pages are selected only at recorded or explicit page breaks.
- `odf_cached_soft_page_breaks_used_for_master_selection`: ODF cached soft page breaks used for master selection; pagination is not recomputed.
- `odf_cell_has_no_supported_cached_value_display_text`: ODF cell has no supported cached value; display text retained.
- `odf_conditional_or_invalid_text_visibility_is_not_evaluated`: ODF conditional or invalid text visibility is not evaluated.
- `odf_conditional_section_visibility_is_not_evaluated_content_retained`: ODF conditional section visibility is not evaluated; content retained.
- `odf_conditional_text_styles_are_not_evaluated_base_style`: ODF conditional text styles are not evaluated; base style used.
- `odf_cyclic_text_visibility_style_available_properties_used`: ODF cyclic text visibility style; available properties used.
- `odf_default_style_is_ambiguous_affected_page_stories_omitted`: ODF default style is ambiguous; affected page stories omitted.
- `odf_disabled_header_footer_omitted`: ODF disabled header/footer omitted.
- `odf_duplicate_default_text_visibility_style_ignored`: ODF duplicate default text visibility style ignored.
- `odf_duplicate_text_visibility_style_ambiguous_properties_ignored`: ODF duplicate text visibility style; ambiguous properties ignored.
- `odf_formulas_are_not_evaluated_only_cached_values_and`: ODF formulas are not evaluated; only cached values and formula text are retained.
- `odf_headers_footers_pooled_from_selected_master_page_variants`: ODF headers/footers pooled from selected master-page variants; page anchors and variant identities are not retained.
- `odf_heading_level_invalid_or_outside_supported_range_1`: ODF heading level invalid or outside supported range 1-9; text retained without heading metadata.
- `odf_hidden_paragraph_has_no_supported_stored_visibility_condition`: ODF hidden paragraph has no supported stored visibility; condition not evaluated.
- `odf_hidden_paragraph_omitted_using_stored_visibility`: ODF hidden paragraph omitted using stored visibility.
- `odf_hidden_section_omitted`: ODF hidden section omitted.
- `odf_hidden_styled_text_omitted`: ODF hidden styled text omitted.
- `odf_initial_master_is_unspecified_using_the_first_stored`: ODF initial master is unspecified; using the first stored master as an implementation-defined fallback.
- `odf_initial_page_sequence_is_ambiguous_page_stories_omitted`: ODF initial page sequence is ambiguous; page stories omitted.
- `odf_inline_text_objects_pooled_with_text_boxes_object`: ODF inline text objects pooled with text boxes; object identity, anchors and embedded page layout are not retained.
- `odf_manifest_missing_package_encryption_declarations_could_not_be`: ODF manifest missing; package encryption declarations could not be checked.
- `odf_master_page_content_is_not_rendered`: ODF master-page content is not rendered.
- `odf_master_reference_is_missing_or_ambiguous_affected_page`: ODF master reference is missing or ambiguous; affected page stories omitted.
- `odf_master_selection_is_ambiguous_missing_duplicate_cyclic_or`: ODF master selection is ambiguous (missing, duplicate, cyclic, or conditional style); affected page stories omitted.
- `odf_page_sequence_selection_uses_its_initial_master_and`: ODF page-sequence selection uses its initial master and recorded page transitions; automatic pagination is not computed.
- `odf_ruby_annotations_omitted_base_text_retained`: ODF ruby annotations omitted; base text retained.
- `odf_shape_text_pooled_with_text_boxes_without_anchor`: ODF shape text pooled with text boxes without anchor or layout identities.
- `odf_slide_headers_footers_dates_and_page_numbers_omitted`: ODF slide headers, footers, dates and page numbers omitted.
- `odf_text_boxes_pooled_without_anchor_chain_or_layout`: ODF text boxes pooled without anchor, chain, or layout identities.
- `odf_text_visibility_style_missing_available_inherited_properties_used`: ODF text visibility style missing; available inherited properties used.
- `odf_unsupported_odf_content_omitted_annotations_revisions_objects_or_extensions`: Unsupported ODF content omitted (annotations, revisions, objects, or extensions).
- `odf_unsupported_odf_spreadsheet_value_type_display_text_retained`: Unsupported ODF spreadsheet value type; display text retained.
- `odf_unsupported_or_malformed_odf_note_omitted`: Unsupported or malformed ODF note omitted.
- `ppt_active_header_footer_fields_have_unresolved_placement_or`: PPT active header/footer fields have unresolved placement or visibility; field text is omitted.
- `ppt_active_master_header_footer_settings_are_not_resolved`: PPT active master header/footer settings are not resolved for slides.
- `ppt_alternate_officeart_xml_is_not_extracted_extension_only`: PPT alternate OfficeArt XML is not extracted; extension-only content may be omitted.
- `ppt_extension_records_are_not_extracted_extension_only_content`: PPT extension records are not extracted; extension-only content may be omitted.
- `ppt_f_ppt_active_name_field_is_not_evaluated_no`: f'PPT active {name} field is not evaluated; no generated value is extracted.'
- `ppt_master_extension_records_are_not_extracted_extension_only`: PPT master extension records are not extracted; extension-only content may be omitted.
- `ppt_slide_local_field_shapes_are_retained_as_stored`: PPT slide-local field shapes are retained as stored text; legacy field text is not merged.
- `ppt_text_field_markers_are_not_evaluated_stored_text`: PPT text field markers are not evaluated; stored text may contain placeholders.
- `ppt_unknown_comment_metadata_is_not_extracted`: PPT unknown comment metadata is not extracted.
- `rtf_a_single_terminal_nul_after_the_rtf_root_was`: A single terminal NUL after the RTF root was ignored.
- `rtf_annotations_omitted`: Annotations omitted.
- `rtf_binary_payload_omitted`: Binary payload omitted.
- `rtf_conflicting_nested_cell_merge_properties_final_flag_used`: Conflicting nested cell merge properties; final flag used.
- `rtf_conflicting_rtf_row_properties_final_properties_used_text_retained`: Conflicting RTF row properties; final properties used, text retained.
- `rtf_control_character_in_wordart_property`: Control character in WordArt property.
- `rtf_cyclic_rtf_style_inheritance_only_available_visibility_properties_used`: Cyclic RTF style inheritance; only available visibility properties used.
- `rtf_depth_zero_inside_unfinished_table_parent_cell_retained`: RTF depth zero inside unfinished table; parent cell retained.
- `rtf_legacy_drawing_and_layout_omitted`: Legacy drawing and layout omitted.
- `rtf_merged_table_cells_retained_as_separate_cells_spans_not`: Merged table cells retained as separate cells; spans not reconstructed.
- `rtf_nested_cell_terminator_missing_text_retained`: Nested cell terminator missing; text retained.
- `rtf_nested_row_properties_missing_cells_retained`: Nested row properties missing; cells retained.
- `rtf_nested_table_row_incomplete_recovered_if_self_level_1`: 'Nested table row incomplete; recovered.' if self.level > 1 else 'Incomplete table row recovered.'
- `rtf_note_destination_in_an_auxiliary_story_omitted`: RTF note destination in an auxiliary story omitted.
- `rtf_pictures_objects_shapes_or_equations_omitted`: Pictures, objects, shapes or equations omitted.
- `rtf_shape_drawing_and_layout_omitted`: Shape drawing and layout omitted.
- `rtf_style_base_missing_or_wrong_kind_only_available`: RTF style base missing or wrong kind; only available visibility properties used.
- `rtf_table_cell_count_differs_from_row_definition`: Table cell count differs from row definition.
- `rtf_table_cell_without_row_definition_recovered`: Table cell without row definition recovered.
- `rtf_unicode_alternate_selected_ansi_alternate_omitted`: Unicode alternate selected; ANSI alternate omitted.
- `rtf_unknown_optional_destinations_omitted`: Unknown optional destinations omitted.
- `rtf_unpaired_unicode_surrogate_replaced`: Unpaired Unicode surrogate replaced.
- `rtf_unsupported_code_page_replaced_with_windows_1252`: Unsupported code page replaced with Windows-1252.
- `rtf_unsupported_font_charset_or_symbol_font_using_document_code`: Unsupported font charset or symbol font; using document code page.
- `rtf_unsupported_or_disabled_wordart_property_text_omitted`: Unsupported or disabled WordArt property text omitted.
- `rtf_vertical_merge_continuation_ambiguous_or_nonempty_cells_retained`: Vertical merge continuation ambiguous or nonempty; cells retained.
- `text_normalized`: Display text normalized; source values and positions retained.
- `unclassified_warning`: Caller-provided warning without a library diagnostic code.
- `xls_excel_date_outside_supported_range_raw_numeric_value_retained`: Excel date outside supported range: raw numeric value retained.
- `xls_formula_expressions_are_not_decoded_or_executed_cached_results`: Formula expressions are not decoded or executed; cached results may be stale.
- `xls_missing_xf_numeric_values_retained_without_date_interpretation`: Missing XF: numeric values retained without date interpretation.
- `xls_non_worksheet_sheets_omitted_charts_macros_vb_modules`: Non-worksheet sheets omitted (charts/macros/VB modules).
- `xls_unrepresentable_excel_date_including_serial_60_raw_numeric_value`: Unrepresentable Excel date (including serial 60): raw numeric value retained.
- `xls_unsupported_or_ambiguous_date_number_format_raw_numeric_value`: Unsupported or ambiguous date/number format: raw numeric value retained.

## DOC auxiliary-story diagnostics

- `doc_header_plc_missing`: Header PLC is absent; retain the whole story without source identities.
- `doc_header_section_count_missing`: Validated section count is absent; retain the whole header story without source identities.
- `doc_textbox_placement_unmodeled`: Textbox source ranges are retained when proven; drawing relationships and page placement are not modeled.

- `odf_sheet_slide_visibility_style_unresolved`: A named sheet/slide visibility style is missing, duplicated or cyclic in its owning document scope; hidden state is not inferred.

- `odf_inline_text_object_projected_to_slide`: recognized direct inline ODF text
  object projected to its owning slide's display destination; object identity
  and layout are not represented.

- `doc_empty_header_plc_ignored`: the header story is empty and all defined
  CPs in its aligned, bounded PLC are zero. The redundant PLC is ignored;
  main content remains available and no header identities are invented.

- `doc_empty_note_plc_ignored`: no note story or reference entries exist, and
  a zero-entry body PLC contains only a zero boundary and undefined sentinel.
- `doc_empty_comment_plc_ignored`: the corresponding empty comment-body case;
  other present author/bookmark metadata still undergoes its normal validation.
