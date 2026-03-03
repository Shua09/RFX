# src/features/supplier_portal/services/bid_submission_service.py

import json
import secrets
from datetime import datetime
from typing import Dict, Any, List, Optional
from ....common.db_pyodbc import get_db_connection
from ....common.logging_config import get_logger

logger = get_logger(__name__)

class BidSubmissionService:
    def __init__(self):
        self.connection = None
        self.cursor = None
    
    def __enter__(self):
        self.connection = get_db_connection()
        self.cursor = self.connection.cursor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
    
    def get_rfq_details_for_supplier(self, mapping_id: int) -> Dict[str, Any]:
        """
        Get RFQ details specifically for the supplier's view
        Updated to allow suppliers to bid on ALL items, with match status as guidance only
        """
        try:
            # Get mapping details with supplier info and matching data
            self.cursor.execute("""
                SELECT 
                    rs.rfq_id,
                    rs.supplier_id,
                    rs.match_score,
                    s.company_name,
                    s.contact_person,
                    s.email,
                    s.brand_representation,
                    s.product_categories,
                    h.total_budget,
                    h.currency,
                    h.required_date,
                    h.delivery_deadline,
                    h.created_at,
                    h.status as rfq_status,
                    rs.matching_items_json,
                    rs.partial_items_json,
                    rs.non_matching_items_json,
                    rs.response_details  -- Added this to check for existing bids
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
                WHERE rs.mapping_id = ?
            """, (mapping_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Mapping not found"}
            
            # Parse matching data
            try:
                matching_items = json.loads(row[14]) if row[14] else []
                partial_items = json.loads(row[15]) if row[15] else []
                non_matching_items = json.loads(row[16]) if row[16] else []
            except:
                matching_items = []
                partial_items = []
                non_matching_items = []
            
            # Parse existing response details if any (using new line_item_bids structure)
            existing_response = {}
            if row[17]:  # response_details column
                try:
                    if isinstance(row[17], str):
                        existing_response = json.loads(row[17])
                    elif isinstance(row[17], dict):
                        existing_response = row[17]
                    else:
                        existing_response = {}
                except:
                    existing_response = {}
            
            # Get ALL RFQ items - no filtering based on matching
            self.cursor.execute("""
                SELECT 
                    line_number,
                    category,
                    brand,
                    model,
                    part_number,
                    description,
                    specifications,
                    quantity,
                    unit_price,
                    total_price,
                    currency
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ?
                ORDER BY line_number
            """, (row[0],))
            
            all_items = []
            for item in self.cursor.fetchall():
                try:
                    specs = json.loads(item[6]) if item[6] else {}
                except:
                    specs = {}
                
                # Determine match status for this item (for guidance only)
                match_status = "none"
                line_num = item[0]
                
                # Check if this item is in matching, partial, or non-matching lists
                if any(m.get('line_number') == line_num for m in matching_items):
                    match_status = "exact"
                elif any(p.get('line_number') == line_num for p in partial_items):
                    match_status = "partial"
                elif any(nm.get('line_number') == line_num for nm in non_matching_items):
                    match_status = "non_matching"
                
                # Check if supplier has already submitted a bid for this line using new structure
                has_existing_bid = False
                existing_bid_data = None
                
                if existing_response and 'line_item_bids' in existing_response:
                    for line_bid in existing_response.get('line_item_bids', []):
                        if line_bid.get('line_number') == line_num:
                            has_existing_bid = True
                            existing_bid_data = {
                                "offered_products": line_bid.get('products_offered', [])
                            }
                            break
                
                item_obj = {
                    "line_number": line_num,
                    "category": item[1] or "",
                    "brand": item[2] or "Any Brand",
                    "model": item[3] or "",
                    "part_number": item[4] or "",
                    "description": item[5] or "",
                    "specifications": specs,
                    "quantity": float(item[7]) if item[7] else 0,
                    "match_status": match_status,  # For guidance only
                    "match_status_display": self._get_match_status_display(match_status),
                    "can_quote": True,  # IMPORTANT: Allow quoting on ALL items
                    "has_existing_bid": has_existing_bid,
                    "existing_bid": existing_bid_data
                }
                
                if item[8] is not None:
                    item_obj["estimated_unit_price"] = float(item[8])
                if item[9] is not None:
                    item_obj["estimated_total_price"] = float(item[9])
                if item[10] is not None:
                    item_obj["currency"] = item[10]
                
                all_items.append(item_obj)
            
            # Check if supplier has already submitted any bid
            has_submitted = False
            submitted_at = None
            self.cursor.execute("""
                SELECT quotation_received, submitted_at 
                FROM [RFQ].[rfq_suppliers]
                WHERE mapping_id = ?
            """, (mapping_id,))
            status_row = self.cursor.fetchone()
            if status_row:
                has_submitted = status_row[0] == 1
                submitted_at = status_row[1]
            
            # Format dates
            required_date = row[10].strftime("%Y-%m-%d") if row[10] else None
            delivery_deadline = row[11].strftime("%Y-%m-%d") if row[11] else None
            created_at = row[12].strftime("%Y-%m-%d") if row[12] else None
            
            # Build line items array with bid status
            line_items = []
            for item in all_items:
                line_item = {
                    "line_number": item["line_number"],
                    "original_request": {
                        "brand": item["brand"],
                        "category": item["category"],
                        "model": item.get("model", ""),
                        "part_number": item.get("part_number", ""),
                        "quantity": item["quantity"],
                        "description": item["description"],
                        "specifications": item["specifications"]
                    },
                    "match_status": item["match_status"],
                    "match_status_display": item["match_status_display"],
                    "can_quote": True,
                    "has_existing_bid": item["has_existing_bid"],
                    "offered_products": item["existing_bid"].get("offered_products", []) if item["has_existing_bid"] else []
                }
                line_items.append(line_item)
            
            return {
                "status": "success",
                "supplier_info": {
                    "contact_person": row[4] or "",
                    "email": row[5] or "",
                    "company_name": row[3] or ""
                },
                "rfq_info": {
                    "rfq_id": row[0],
                    "currency": row[9] or "USD",
                    "required_date": required_date,
                    "delivery_deadline": delivery_deadline,
                    "created_at": created_at,
                    "total_budget": float(row[8]) if row[8] else None,
                    "status": row[13]
                },
                "match_info": {
                    "match_score": float(row[2]) if row[2] else 0,
                    "matching_items_count": len(matching_items),
                    "partial_items_count": len(partial_items),
                    "non_matching_items_count": len(non_matching_items)
                },
                "items": all_items,
                "line_items": line_items,  # Clean structure for the frontend
                "has_submitted": has_submitted,
                "submitted_at": submitted_at.strftime("%Y-%m-%d %H:%M:%S") if submitted_at else None,
                "item_count": len(all_items),
                "guidance_note": "You can bid on any item. Match status is shown for guidance only."
            }
            
        except Exception as e:
            logger.error(f"Error getting RFQ details: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def _get_match_status_display(self, status: str) -> Dict[str, Any]:
        """Get display information for match status"""
        status_display = {
            "exact": {
                "label": "Excellent Match",
                "color": "green",
                "description": "This item matches your registered products/brands",
                "icon": "✅",
                "recommendation": "Highly recommended to bid"
            },
            "partial": {
                "label": "Partial Match",
                "color": "orange",
                "description": "This item partially matches your registered products/brands",
                "icon": "⚠️",
                "recommendation": "Consider bidding if you can supply"
            },
            "non_matching": {
                "label": "Not in Your Profile",
                "color": "red",
                "description": "This item doesn't match your registered products/brands",
                "icon": "ℹ️",
                "recommendation": "Bid only if you can supply these items"
            },
            "none": {
                "label": "New Category",
                "color": "blue",
                "description": "This is a new category not in your profile",
                "icon": "🆕",
                "recommendation": "Opportunity to expand your business"
            }
        }
        return status_display.get(status, status_display["none"])
    
    def submit_bid(self, mapping_id: int, supplier_id: int, rfq_id: str, 
           bid_data: Any) -> Dict[str, Any]:
        """
        Submit a bid/quote for the RFQ
        Enhanced to support per-product split awards with detailed line item data
        """
        try:
            # Log the incoming data type and content
            logger.info(f"=== Starting submit_bid ===")
            logger.info(f"submit_bid received - mapping_id: {mapping_id}, supplier_id: {supplier_id}, rfq_id: {rfq_id}")
            logger.info(f"bid_data type: {type(bid_data)}")
            
            if isinstance(bid_data, str):
                logger.info("bid_data is string, parsing...")
                try:
                    bid_data = json.loads(bid_data)
                    logger.info("Successfully parsed JSON")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse bid_data JSON: {str(e)}")
                    return {
                        "status": "error",
                        "message": "Invalid bid data format"
                    }
            elif isinstance(bid_data, dict):
                logger.info(f"bid_data is dictionary with keys: {list(bid_data.keys())}")
            else:
                logger.error(f"Unexpected bid_data type: {type(bid_data)}")
                return {
                    "status": "error",
                    "message": f"Bid data must be a dictionary or string, got {type(bid_data)}"
                }
            
            # Check if this supplier has already submitted
            logger.info("Checking existing submission...")
            self.cursor.execute("""
                SELECT quotation_received, response_details, submitted_at
                FROM [RFQ].[rfq_suppliers]
                WHERE mapping_id = ? AND supplier_id = ?
            """, (mapping_id, supplier_id))
            
            existing = self.cursor.fetchone()
            logger.info(f"Existing submission: {existing}")
            
            # If already submitted, check if we're updating
            if existing and existing[0] == 1:
                logger.info("Existing submission found, checking RFQ status...")
                self.cursor.execute("""
                    SELECT status FROM [RFQ].[rfq_headers]
                    WHERE rfq_id = ?
                """, (rfq_id,))
                rfq_status_row = self.cursor.fetchone()
                if rfq_status_row:
                    rfq_status = rfq_status_row[0]
                    logger.info(f"RFQ status: {rfq_status}")
                    if rfq_status not in ['PUBLISHED', 'OPEN']:
                        return {
                            "status": "error",
                            "message": "Bid submission is closed for this RFQ"
                        }
            
            # Process quotations with enhanced line item details
            logger.info("Getting quotations from bid_data...")
            quotations = bid_data.get('quotations', [])
            logger.info(f"Number of quotations: {len(quotations)}")
            logger.info(f"Quotations type: {type(quotations)}")
            
            total_amount = 0
            items_bid_on = 0
            
            # Enhanced bid tracking per line item
            line_item_bids = []
            
            for idx, q in enumerate(quotations):
                logger.info(f"Processing quotation {idx}, type: {type(q)}")
                
                # Add type checking for q
                if not isinstance(q, dict):
                    logger.error(f"Quotation {idx} is not a dict, it's a {type(q)}")
                    logger.error(f"Quotation value: {q}")
                    continue
                
                line_number = q.get('line_number')
                original_request = q.get('original_request', {})
                offered_products = q.get('offered_products', [])
                
                logger.info(f"Line {line_number}: original_request type: {type(original_request)}")
                logger.info(f"Line {line_number}: offered_products type: {type(offered_products)}")
                logger.info(f"Line {line_number}: offered_products count: {len(offered_products)}")
                
                # Ensure offered_products is a list
                if not isinstance(offered_products, list):
                    logger.error(f"offered_products is not a list for line {line_number}, it's a {type(offered_products)}")
                    offered_products = []
                
                line_total = 0
                products_detail = []
                
                for p_idx, product in enumerate(offered_products):
                    logger.info(f"Processing product {p_idx} for line {line_number}, type: {type(product)}")
                    
                    # Add type checking for product
                    if not isinstance(product, dict):
                        logger.error(f"Product {p_idx} is not a dict, it's a {type(product)}")
                        logger.error(f"Product value: {product}")
                        continue
                    
                    # Safely get values with defaults
                    try:
                        quantity = float(product.get('quantity', 0) or 0)
                        logger.info(f"Product {p_idx} quantity: {quantity}")
                    except (ValueError, TypeError) as e:
                        logger.error(f"Error parsing quantity for product {p_idx}: {e}")
                        quantity = 0
                        
                    try:
                        unit_price = float(product.get('unit_price', 0) or 0)
                        logger.info(f"Product {p_idx} unit_price: {unit_price}")
                    except (ValueError, TypeError) as e:
                        logger.error(f"Error parsing unit_price for product {p_idx}: {e}")
                        unit_price = 0
                    
                    product_total = quantity * unit_price
                    line_total += product_total
                    
                    # Track individual product details for split awards
                    product_detail = {
                        "product_name": product.get('product_name', product.get('model', '')),
                        "brand": product.get('brand', original_request.get('brand', '')),
                        "model": product.get('model', ''),
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "total_price": product_total,
                        "delivery_date": product.get('delivery_date'),
                        "delivery_time_days": product.get('delivery_time_days', 0),
                        "warranty": product.get('warranty', product.get('warranty_months', 0)),
                        "notes": product.get('notes', '')
                    }
                    products_detail.append(product_detail)
                
                total_amount += line_total
                items_bid_on += len(products_detail)
                
                # Store detailed line item bid for award processing
                try:
                    requested_qty = float(original_request.get('quantity', 0) or 0)
                    offered_qtys = [p.get('quantity', 0) for p in products_detail]
                    
                    line_item_bids.append({
                        "line_number": line_number,
                        "original_request": {
                            "category": original_request.get('category'),
                            "brand": original_request.get('brand'),
                            "model": original_request.get('model'),
                            "part_number": original_request.get('part_number'),
                            "quantity": requested_qty,
                            "description": original_request.get('description', '')
                        },
                        "match_status": q.get('match_status', 'unknown'),
                        "products_offered": products_detail,
                        "line_total": line_total,
                        "currency": bid_data.get('summary', {}).get('currency', 'USD'),
                        "can_fulfill_fully": all(p.get('quantity', 0) >= requested_qty for p in products_detail),
                        "fulfillment_percentage": self._calculate_fulfillment_percentage(
                            requested_qty,
                            offered_qtys
                        )
                    })
                    logger.info(f"Successfully added line item bid for line {line_number}")
                except Exception as e:
                    logger.error(f"Error creating line item bid for line {line_number}: {str(e)}")
            
            logger.info(f"Total amount: {total_amount}, items bid on: {items_bid_on}")
            logger.info(f"Number of line_item_bids: {len(line_item_bids)}")
            
            logger.info(f"Total amount: {total_amount}, items bid on: {items_bid_on}")
            logger.info(f"Number of line_item_bids: {len(line_item_bids)}")
            
            # Prepare enhanced bid summary for award processing
            logger.info("Preparing bid summary...")
            summary_data = bid_data.get('summary', {})
            logger.info(f"Summary data type: {type(summary_data)}")
            logger.info(f"Summary data: {summary_data}")
            
            # Check if summary_data is None or not a dict
            if summary_data is None:
                logger.error("summary_data is None")
                summary_data = {}
            elif not isinstance(summary_data, dict):
                logger.error(f"summary_data is not a dict, it's a {type(summary_data)}")
                summary_data = {}
            
            # Safely get currency
            currency = summary_data.get('currency', 'USD')
            logger.info(f"Currency: {currency}")
            
            bid_summary = {
                "total_amount": total_amount,
                "currency": currency,
                "items_bid_on": items_bid_on,
                "total_line_items": len(quotations),
                "submission_type": "partial" if any(not item.get('can_fulfill_fully', False) for item in line_item_bids) else "full",
                "delivery_terms": summary_data.get('delivery_terms', ''),
                "payment_terms": summary_data.get('payment_terms', ''),
                "valid_until": summary_data.get('valid_until'),
                "additional_notes": summary_data.get('notes', '')
            }
            logger.info(f"Bid summary created: {bid_summary}")
            
            # Calculate delivery commitment summary
            logger.info("Calculating delivery dates...")
            delivery_dates = []
            for item_idx, item in enumerate(line_item_bids):
                logger.info(f"Processing item {item_idx} for delivery dates")
                products = item.get('products_offered', [])
                logger.info(f"Products in item: {len(products)}")
                
                for product_idx, product in enumerate(products):
                    logger.info(f"Processing product {product_idx}")
                    
                    if product.get('delivery_date'):
                        delivery_dates.append(product['delivery_date'])
                        logger.info(f"Added delivery date: {product['delivery_date']}")
                    elif product.get('delivery_time_days'):
                        # Calculate estimated delivery date
                        from datetime import datetime, timedelta
                        delivery_days = product.get('delivery_time_days', 0)
                        est_date = (datetime.now() + timedelta(days=delivery_days)).strftime('%Y-%m-%d')
                        delivery_dates.append(est_date)
                        logger.info(f"Added estimated delivery date: {est_date} (from {delivery_days} days)")
            
            logger.info(f"Total delivery dates collected: {len(delivery_dates)}")
            
            # Store the enhanced bid as JSON
            logger.info("Creating response_details JSON...")
            supplier_info = bid_data.get('supplier_info', {})
            logger.info(f"Supplier info type: {type(supplier_info)}")
            
            if supplier_info is None:
                supplier_info = {}
            
            try:
                response_details = json.dumps({
                    "supplier_info": {
                        **supplier_info,
                        "submission_id": f"SUB-{mapping_id}-{int(datetime.now().timestamp())}"
                    },
                    "line_item_bids": line_item_bids,
                    "summary": bid_summary,
                    "delivery_summary": {
                        "earliest_delivery": min(delivery_dates) if delivery_dates else None,
                        "latest_delivery": max(delivery_dates) if delivery_dates else None,
                        "commitment_date": summary_data.get('delivery_terms', {}).get('commitment_date') if isinstance(summary_data.get('delivery_terms'), dict) else None
                    },
                    "submitted_at": datetime.now().isoformat(),
                    "last_updated": datetime.now().isoformat(),
                    "version": "2.0"
                }, default=str)
                logger.info("Response details JSON created successfully")
            except Exception as e:
                logger.error(f"Error creating response_details JSON: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                raise
            
            # Also store line-item level data in a separate table for easier award processing
            logger.info("Storing line item bids...")
            self._store_line_item_bids(mapping_id, rfq_id, line_item_bids)
            
            # Determine if this is insert or update
            logger.info(f"Determining action based on existing: {existing}")
            if existing and existing[0] == 1:
                logger.info("Updating existing bid...")
                # Update existing bid
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_suppliers]
                    SET 
                        response_details = ?,
                        quotation_amount = ?,
                        quotation_currency = ?,
                        status = ?,
                        updated_at = GETDATE(),
                        resubmitted_at = GETDATE(),
                        resubmission_count = ISNULL(resubmission_count, 0) + 1
                    WHERE mapping_id = ? AND supplier_id = ?
                """, (
                    response_details,
                    total_amount,
                    bid_summary['currency'],
                    'RESUBMITTED',
                    mapping_id,
                    supplier_id
                ))
                action = "updated"
                logger.info("Update executed")
            else:
                logger.info("Inserting new bid...")
                # Insert new bid
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_suppliers]
                    SET 
                        response_received = 1,
                        response_details = ?,
                        quotation_received = 1,
                        quotation_amount = ?,
                        quotation_currency = ?,
                        status = ?,
                        submitted_at = GETDATE(),
                        updated_at = GETDATE()
                    WHERE mapping_id = ? AND supplier_id = ?
                """, (
                    response_details,
                    total_amount,
                    bid_summary['currency'],
                    'SUBMITTED',
                    mapping_id,
                    supplier_id
                ))
                action = "submitted"
                logger.info("Insert executed")
            
            self.connection.commit()
            logger.info("Transaction committed")
            
            return {
                "status": "success",
                "submission_id": f"BID-{mapping_id}-{int(datetime.now().timestamp())}",
                "total_amount": total_amount,
                "currency": bid_summary['currency'],
                "items_bid_on": items_bid_on,
                "action": action,
                "message": f"Bid {action} successfully",
                "bid_structure": {
                    "supports_split_awards": True,
                    "line_item_count": len(line_item_bids),
                    "fulfillment_type": bid_summary['submission_type']
                }
            }
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error submitting bid: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "message": str(e)
            }

    def _calculate_fulfillment_percentage(self, requested_qty: float, offered_quantities: List[float]) -> float:
        """Calculate what percentage of the requested quantity can be fulfilled"""
        if not requested_qty or requested_qty == 0:
            return 0
        total_offered = sum(offered_quantities)
        percentage = (total_offered / requested_qty) * 100
        return min(round(percentage, 2), 100)

    def _store_line_item_bids(self, mapping_id: int, rfq_id: str, line_item_bids: List[Dict]):
        """Store line-item level bid data for easier award processing"""
        try:
            # First, check if the table exists
            self.cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='rfq_line_item_bids' AND xtype='U')
                CREATE TABLE [RFQ].[rfq_line_item_bids] (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    mapping_id INT NOT NULL,
                    rfq_id NVARCHAR(50) NOT NULL,
                    line_number INT NOT NULL,
                    supplier_id INT NOT NULL,
                    product_data NVARCHAR(MAX),
                    unit_price DECIMAL(18,2),
                    total_price DECIMAL(18,2),
                    quantity_offered DECIMAL(18,2),
                    delivery_days INT,
                    created_at DATETIME2 DEFAULT GETDATE(),
                    FOREIGN KEY (mapping_id) REFERENCES [RFQ].[rfq_suppliers](mapping_id)
                )
            """)
            self.connection.commit()
            
            # Clear existing line item bids for this mapping
            self.cursor.execute("""
                DELETE FROM [RFQ].[rfq_line_item_bids]
                WHERE mapping_id = ?
            """, (mapping_id,))
            
            # Insert new line item bids
            for item in line_item_bids:
                line_number = item['line_number']
                for product in item['products_offered']:
                    self.cursor.execute("""
                        INSERT INTO [RFQ].[rfq_line_item_bids]
                        (mapping_id, rfq_id, line_number, supplier_id, product_data, 
                        unit_price, total_price, quantity_offered, delivery_days, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
                    """, (
                        mapping_id,
                        rfq_id,
                        line_number,
                        self._get_supplier_id_from_mapping(mapping_id),
                        json.dumps(product, default=str),
                        product.get('unit_price', 0),
                        product.get('total_price', 0),
                        product.get('quantity', 0),
                        product.get('delivery_time_days')
                    ))
            
            self.connection.commit()
            
        except Exception as e:
            logger.error(f"Error storing line item bids: {str(e)}")
            # Don't raise - this is non-critical

    def _get_supplier_id_from_mapping(self, mapping_id: int) -> int:
        """Helper to get supplier_id from mapping_id"""
        try:
            self.cursor.execute("""
                SELECT supplier_id FROM [RFQ].[rfq_suppliers]
                WHERE mapping_id = ?
            """, (mapping_id,))
            row = self.cursor.fetchone()
            return row[0] if row else None
        except:
            return None
    
    def get_submitted_bid(self, mapping_id: int) -> Dict[str, Any]:
        """
        Get a previously submitted bid for viewing
        Retrieves from response_details JSON using new line_item_bids structure
        """
        try:
            self.cursor.execute("""
                SELECT 
                    rs.rfq_id,
                    rs.supplier_id,
                    rs.response_details,
                    rs.quotation_amount,
                    rs.quotation_currency,
                    rs.submitted_at,
                    rs.status,
                    rs.resubmitted_at,
                    rs.resubmission_count,
                    s.company_name,
                    s.contact_person,
                    s.email,
                    h.required_date,
                    h.delivery_deadline,
                    h.created_at
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
                WHERE rs.mapping_id = ?
            """, (mapping_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {
                    "status": "error",
                    "message": "No bid found"
                }
            
            # Parse response_details JSON
            try:
                bid_data = json.loads(row[2]) if row[2] else {}
            except:
                bid_data = {}
            
            # Calculate items bid on from line_item_bids structure
            items_bid_on = 0
            if bid_data and 'line_item_bids' in bid_data:
                for line_bid in bid_data['line_item_bids']:
                    items_bid_on += len(line_bid.get('products_offered', []))
            
            return {
                "status": "success",
                "supplier_info": {
                    "company_name": row[9],
                    "contact_person": row[10],
                    "email": row[11],
                    "submitted_at": row[5].strftime("%Y-%m-%d %H:%M:%S") if row[5] else None,
                    "resubmitted_at": row[7].strftime("%Y-%m-%d %H:%M:%S") if row[7] else None,
                    "resubmission_count": row[8] or 0
                },
                "rfq_info": {
                    "rfq_id": row[0],
                    "required_date": row[12].strftime("%Y-%m-%d") if row[12] else None,
                    "delivery_deadline": row[13].strftime("%Y-%m-%d") if row[13] else None,
                    "created_at": row[14].strftime("%Y-%m-%d") if row[14] else None
                },
                "bid_data": bid_data,
                "summary": {
                    "total_amount": float(row[3]) if row[3] else 0,
                    "currency": row[4] or "USD",
                    "items_bid_on": items_bid_on
                },
                "status": row[6]
            }
            
        except Exception as e:
            logger.error(f"Error getting submitted bid: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def get_submission_confirmation(self, mapping_id: int) -> Dict[str, Any]:
        """
        Get confirmation details for a submitted bid
        """
        try:
            self.cursor.execute("""
                SELECT 
                    rs.rfq_id,
                    rs.quotation_amount,
                    rs.quotation_currency,
                    rs.submitted_at,
                    s.company_name,
                    rs.status,
                    h.required_date,
                    h.delivery_deadline,
                    rs.response_details
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
                WHERE rs.mapping_id = ?
            """, (mapping_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {
                    "status": "error",
                    "message": "Submission not found"
                }
            
            # Count items bid on from line_item_bids structure
            items_bid_on = 0
            try:
                bid_data = json.loads(row[8]) if row[8] else {}
                if bid_data and 'line_item_bids' in bid_data:
                    for line_bid in bid_data['line_item_bids']:
                        items_bid_on += len(line_bid.get('products_offered', []))
            except:
                pass
            
            return {
                "status": "success",
                "rfq_id": row[0],
                "total_amount": float(row[1]) if row[1] else 0,
                "currency": row[2],
                "submitted_at": row[3].strftime("%Y-%m-%d %H:%M:%S") if row[3] else None,
                "company_name": row[4],
                "status": row[5],
                "required_date": row[6].strftime("%Y-%m-%d") if row[6] else None,
                "delivery_deadline": row[7].strftime("%Y-%m-%d") if row[7] else None,
                "items_bid_on": items_bid_on,
                "message": "Your bid has been successfully submitted. You will be notified when a decision is made."
            }
            
        except Exception as e:
            logger.error(f"Error getting confirmation: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def check_bid_status(self, mapping_id: int) -> Dict[str, Any]:
        """
        Check the status of a bid (for suppliers to track)
        """
        try:
            self.cursor.execute("""
                SELECT 
                    rs.status,
                    rs.submitted_at,
                    rs.quotation_amount,
                    rs.quotation_currency,
                    h.status as rfq_status,
                    h.required_date
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
                WHERE rs.mapping_id = ?
            """, (mapping_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Bid not found"}
            
            status_display = {
                'SUBMITTED': 'Under Review',
                'RESUBMITTED': 'Updated - Under Review',
                'UNDER_REVIEW': 'Under Review',
                'AWARDED': 'Won',
                'LOST': 'Not Selected',
                'PARTIAL': 'Partially Awarded'
            }
            
            return {
                "status": "success",
                "bid_status": row[0],
                "bid_status_display": status_display.get(row[0], row[0]),
                "submitted_at": row[1].strftime("%Y-%m-%d %H:%M:%S") if row[1] else None,
                "bid_amount": float(row[2]) if row[2] else 0,
                "currency": row[3] or "USD",
                "rfq_status": row[4],
                "required_date": row[5].strftime("%Y-%m-%d") if row[5] else None
            }
            
        except Exception as e:
            logger.error(f"Error checking bid status: {str(e)}")
            return {"status": "error", "message": str(e)}